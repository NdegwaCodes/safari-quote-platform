from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.operations.actuals import (
    MODEL_OPTIMISTIC,
    MODEL_PESSIMISTIC,
    NOT_ENOUGH_DATA,
    Actual,
    Fill,
    LogRefused,
    Odometer,
    audit,
    check_fill,
    check_reading,
    fuel_total,
    measure,
)

D = Decimal


def _fill(litres="60", amount="10800", currency="KES"):
    return Fill(
        litres=D(litres),
        amount=D(amount),
        currency=currency,
        bought_on=date(2026, 11, 4),
    )


def test_distance_is_the_difference():
    assert Odometer(out_km=D("84300"), in_km=D("85210")).distance == D("910")


def test_a_vehicle_still_out_has_no_distance_yet():
    assert Odometer(out_km=D("84300")).distance is None


def test_an_odometer_does_not_run_backwards():
    with pytest.raises(LogRefused) as raised:
        check_reading(Odometer(out_km=D("84300"), in_km=D("83210")))
    assert "does not run backwards" in str(raised.value)
    assert "84300" in str(raised.value)


def test_leaving_on_less_than_the_last_return_is_impossible():
    with pytest.raises(LogRefused) as raised:
        check_reading(Odometer(out_km=D("84000")), previous_in=D("84300"))
    assert "One of the two readings is wrong" in str(raised.value)


def test_kilometres_between_trips_are_observed_and_not_refused():
    notes = check_reading(Odometer(out_km=D("84910")), previous_in=D("84300"))
    assert len(notes) == 1
    assert "610 km since the vehicle last came back" in notes[0]
    assert "somebody's weekend" in notes[0]


def test_a_vehicle_leaving_on_exactly_its_last_reading_says_nothing():
    assert check_reading(Odometer(out_km=D("84300")), previous_in=D("84300")) == []


def test_a_negative_reading_is_refused():
    with pytest.raises(LogRefused):
        check_reading(Odometer(out_km=D("-1")))


def test_a_receipt_needs_litres_as_well_as_money():
    with pytest.raises(LogRefused) as raised:
        check_fill(_fill(litres="0"))
    assert "has to have litres on it" in str(raised.value)


def test_a_receipt_needs_a_currency():
    with pytest.raises(LogRefused) as raised:
        check_fill(Fill(litres=D("60"), amount=D("10800"), currency=""))
    assert "needs a currency" in str(raised.value)


def test_the_litre_price_is_derived_for_reading_and_never_stored():
    assert _fill(litres="60", amount="10800").price_per_litre == D("180.00")


def test_fuel_across_a_trip_is_totalled():
    litres, amount, currency = fuel_total(
        [_fill(litres="60", amount="10800"), _fill(litres="45", amount="8325")]
    )
    assert litres == D("105")
    assert amount == D("19125")
    assert currency == "KES"


def test_fuel_bought_in_two_currencies_is_refused_not_converted():
    with pytest.raises(LogRefused) as raised:
        fuel_total([_fill(currency="KES"), _fill(currency="TZS")])
    assert "KES, TZS" in str(raised.value)
    assert "a decision and not arithmetic" in str(raised.value)


def test_no_receipts_is_zero_and_not_an_error():
    assert fuel_total([]) == (D(0), D(0), "")


def test_a_trip_is_measured_against_the_model():
    actual = measure(
        odometer=Odometer(out_km=D("84300"), in_km=D("85210")),
        fills=[_fill(litres="130", amount="23400")],
        model_kmpl=D("8.5"),
    )
    assert actual.distance_km == D("910")
    assert actual.litres == D("130")
    assert actual.fuel_cost == D("23400")
    assert actual.actual_kmpl == D("7.00")
    assert actual.model_litres == D("107.06")
    assert actual.variance_pct == D("-17.65")


def test_beating_the_model_is_the_harmless_direction():
    actual = measure(
        odometer=Odometer(out_km=D("0"), in_km=D("900")),
        fills=[_fill(litres="90", amount="16200")],
        model_kmpl=D("8.5"),
    )
    assert actual.actual_kmpl == D("10.00")
    assert actual.variance_pct > 0


def test_a_trip_too_short_to_mean_anything_reports_no_consumption():
    actual = measure(
        odometer=Odometer(out_km=D("84300"), in_km=D("84340")),
        fills=[_fill(litres="13", amount="2340")],
        model_kmpl=D("8.5"),
    )
    assert actual.distance_km == D("40")
    assert actual.actual_kmpl is None
    assert actual.variance_pct is None


def test_a_trip_with_no_receipts_has_a_distance_and_no_consumption():
    actual = measure(
        odometer=Odometer(out_km=D("84300"), in_km=D("85210")),
        fills=[],
        model_kmpl=D("8.5"),
    )
    assert actual.distance_km == D("910")
    assert actual.actual_kmpl is None


def test_a_vehicle_still_out_is_not_measured_yet():
    actual = measure(
        odometer=Odometer(out_km=D("84300")),
        fills=[_fill()],
        model_kmpl=D("8.5"),
    )
    assert actual.distance_km is None
    assert actual.actual_kmpl is None
    assert actual.litres == D("60")


def _actual(km, litres, model="8.5"):
    return Actual(
        distance_km=D(km),
        litres=D(litres),
        fuel_cost=D(litres) * D("180"),
        currency="KES",
        model_kmpl=D(model),
        actual_kmpl=(D(km) / D(litres)).quantize(D("0.01")),
    )


def test_a_model_that_is_out_says_so_and_says_by_how_much():
    truth = audit(
        "KBZ 123A",
        [_actual("910", "130"), _actual("1200", "170"), _actual("800", "115")],
        model_kmpl=D("8.5"),
    )
    assert truth.trips == 3
    assert truth.actual_kmpl == D("7.01")
    finding = next(one for one in truth.findings if one.code == MODEL_OPTIMISTIC)
    assert "priced at 8.5 km/L and has managed 7.01" in finding.message
    assert "under-costing fuel by about 17.5%" in finding.message
    assert "nothing here changes it" in finding.message


def test_the_audit_reports_and_never_applies():
    truth = audit(
        "KBZ 123A",
        [_actual("910", "130"), _actual("1200", "170"), _actual("800", "115")],
        model_kmpl=D("8.5"),
    )
    finding = truth.findings[0]
    assert finding.model_kmpl == D("8.5")
    assert finding.actual_kmpl == D("7.01")
    assert truth.model_kmpl == D("8.5")


def test_a_model_that_over_costs_is_reported_differently():
    truth = audit(
        "KBZ 123A",
        [_actual("1100", "100"), _actual("1200", "110"), _actual("900", "82")],
        model_kmpl=D("8.5"),
    )
    finding = next(one for one in truth.findings if one.code == MODEL_PESSIMISTIC)
    assert "more fuel than it burns" in finding.message
    assert "losing work on price" in finding.message


def test_a_model_within_tolerance_is_left_alone():
    truth = audit(
        "KBZ 123A",
        [_actual("850", "100"), _actual("880", "103"), _actual("820", "97")],
        model_kmpl=D("8.5"),
    )
    assert truth.findings == []


def test_two_trips_and_a_hill_is_not_a_pattern():
    truth = audit(
        "KBZ 123A", [_actual("910", "130"), _actual("1200", "170")],
        model_kmpl=D("8.5"),
    )
    finding = next(one for one in truth.findings if one.code == NOT_ENOUGH_DATA)
    assert "2 measured trip(s)" in finding.message
    assert "is not a pattern" in finding.message


def test_consumption_is_pooled_rather_than_averaged_per_trip():
    truth = audit(
        "KBZ 123A",
        [_actual("120", "30"), _actual("1400", "160"), _actual("1300", "150")],
        model_kmpl=D("8.5"),
    )
    assert truth.actual_kmpl == D("8.29")
    assert truth.findings == []


def test_a_vehicle_with_no_measured_trips_says_so():
    truth = audit("KBZ 123A", [], model_kmpl=D("8.5"))
    assert truth.trips == 0
    assert [one.code for one in truth.findings] == [NOT_ENOUGH_DATA]


def test_trips_still_out_are_not_counted():
    truth = audit(
        "KBZ 123A",
        [
            _actual("910", "130"),
            _actual("1200", "170"),
            _actual("800", "115"),
            Actual(distance_km=None, litres=D("60"), model_kmpl=D("8.5")),
        ],
        model_kmpl=D("8.5"),
    )
    assert truth.trips == 3
