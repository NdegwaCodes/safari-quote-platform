from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.portal.view import (
    CANCELLED,
    EXPIRED,
    REVOKED,
    AccessRefused,
    Grant,
    check_access,
    default_expiry,
    option_of,
    trip_of,
)

D = Decimal
TODAY = date(2026, 9, 4)


def _snapshot(**over):
    option = {
        "option_id": "11111111-1111-1111-1111-111111111111",
        "accommodation_id": "22222222-2222-2222-2222-222222222222",
        "accommodation_name": "Reef House",
        "room_type_name": "Garden Twin",
        "meal_plan_code": "HB",
        "meal_plan_name": "Half Board",
        "nights": 3,
        "is_recommended": True,
        "sort_order": 0,
        "blurb": "A quiet house set back from the beach.",
        "activities": ["Dhow sunset cruise", "Snorkelling at the reef"],
        "components": {"accommodation": "180000.00", "transport": "42000.00"},
        "supplier_paid_total": "222000.00",
        "retained_discount": "5000.00",
        "cost_subtotal": "222000.00",
        "contingency_value": "6660.00",
        "profit_value": "57000.00",
        "agent_cover_fee": "0.00",
        "per_person": "94330.00",
        "group_total": "285660.00",
        "client_total": "285660.00",
        "warnings": ["A cost warning nobody outside should read"],
        "legs": [
            {
                "sequence": 1,
                "accommodation_name": "Reef House",
                "destination_name": "Diani",
                "room_type_name": "Garden Twin",
                "meal_plan_name": "Half Board",
                "rooms_required": 2,
                "nights": 3,
            }
        ],
        "days": [
            {
                "number": 1,
                "date": "2026-11-02",
                "destination": "Diani",
                "property_name": "Reef House",
                "board": "HB",
                "movements": [{"label": "Mombasa to Diani", "minutes": 90}],
                "excursions": [],
                "is_arrival": True,
                "is_departure": False,
                "has_night": True,
            },
            {
                "number": 2,
                "date": "2026-11-03",
                "destination": "Diani",
                "property_name": "Reef House",
                "board": "HB",
                "movements": [],
                "excursions": ["Dhow sunset cruise"],
                "is_arrival": False,
                "is_departure": False,
                "has_night": True,
            },
        ],
    }
    option.update(over)
    return {
        "quote_number": "HTQ-2026-0031",
        "currency": "KES",
        "arrival_date": "2026-11-02",
        "departure_date": "2026-11-05",
        "pax_count": 4,
        "options": [option],
    }


def _trip(snapshot=None, **over):
    fields = {
        "option_id": "11111111-1111-1111-1111-111111111111",
        "reference": "HTB-2026-0007",
        "status": "confirmed",
        "arrival": date(2026, 11, 2),
        "departure": date(2026, 11, 5),
        "pax_count": 4,
        "total": D("285660.00"),
        "currency": "KES",
    }
    fields.update(over)
    return trip_of(snapshot if snapshot is not None else _snapshot(), **fields)


INTERNAL_KEYS = (
    "components",
    "supplier_paid_total",
    "retained_discount",
    "cost_subtotal",
    "contingency_value",
    "profit_value",
    "agent_cover_fee",
    "per_person",
    "group_total",
    "client_total",
    "warnings",
)


def test_no_internal_figure_reaches_the_client_view():
    trip = _trip()
    flat = repr(vars(trip))
    for key in INTERNAL_KEYS:
        assert key not in flat, key
    for figure in ("222000", "57000", "6660", "5000", "94330"):
        assert figure not in flat, figure
    assert "nobody outside should read" not in flat


def test_a_costing_field_added_to_the_snapshot_tomorrow_does_not_leak():
    trip = _trip(_snapshot(margin_after_rebate="99999.00", supplier_ref="ACME-77"))
    flat = repr(vars(trip))
    assert "99999" not in flat
    assert "ACME-77" not in flat


def test_the_money_shown_is_the_bookings_and_not_the_snapshots():
    trip = _trip(total=D("300000.00"))
    assert trip.total == D("300000.00")
    assert trip.currency == "KES"


def test_the_trip_is_the_option_they_booked():
    trip = _trip()
    assert trip.reference == "HTB-2026-0007"
    assert trip.property_name == "Reef House"
    assert trip.board == "Half Board"
    assert trip.nights == 3
    assert trip.description == "A quiet house set back from the beach."
    assert trip.included == ["Dhow sunset cruise", "Snorkelling at the reef"]


def test_only_the_booked_option_appears():
    snapshot = _snapshot()
    second = dict(snapshot["options"][0])
    second["option_id"] = "33333333-3333-3333-3333-333333333333"
    second["accommodation_name"] = "The one they did not pick"
    second["is_recommended"] = False
    snapshot["options"].append(second)

    trip = _trip(snapshot)
    assert trip.property_name == "Reef House"
    assert "did not pick" not in repr(vars(trip))


def test_a_booking_with_no_option_falls_back_to_the_recommended_one():
    snapshot = _snapshot()
    second = dict(snapshot["options"][0])
    second["option_id"] = "33333333-3333-3333-3333-333333333333"
    second["accommodation_name"] = "Second choice"
    second["is_recommended"] = False
    snapshot["options"] = [second, snapshot["options"][0]]

    trip = _trip(snapshot, option_id=None)
    assert trip.property_name == "Reef House"


def test_an_option_id_that_is_not_in_the_snapshot_does_not_produce_nothing():
    trip = _trip(option_id="99999999-9999-9999-9999-999999999999")
    assert trip.property_name == "Reef House"


def test_a_snapshot_with_no_options_is_an_empty_trip_and_not_a_crash():
    trip = _trip({"options": []})
    assert trip.property_name == ""
    assert trip.days == []
    assert trip.reference == "HTB-2026-0007"


def test_the_programme_comes_through_in_order():
    trip = _trip()
    assert [day.number for day in trip.days] == [1, 2]
    assert trip.days[0].is_arrival is True
    assert trip.days[0].movements[0].label == "Mombasa to Diani"
    assert trip.days[0].movements[0].minutes == 90
    assert trip.days[1].excursions == ["Dhow sunset cruise"]


def test_movements_frozen_before_the_route_table_still_read():
    snapshot = _snapshot()
    snapshot["options"][0]["days"][0]["movements"] = ["Mombasa to Diani"]
    trip = _trip(snapshot)
    assert trip.days[0].movements[0].label == "Mombasa to Diani"
    assert trip.days[0].movements[0].minutes is None


def test_a_malformed_day_is_skipped_rather_than_raising():
    snapshot = _snapshot()
    snapshot["options"][0]["days"].append("not a day")
    snapshot["options"][0]["days"][0]["date"] = "the second of November"
    trip = _trip(snapshot)
    assert len(trip.days) == 2
    assert trip.days[0].on is None


def test_the_stays_carry_each_property_and_its_nights():
    trip = _trip()
    assert [stay.property_name for stay in trip.stays] == ["Reef House"]
    assert trip.stays[0].destination == "Diani"
    assert trip.stays[0].rooms == 2


def test_option_of_is_usable_on_its_own():
    assert option_of(_snapshot(), None)["accommodation_name"] == "Reef House"
    assert option_of({}, None) == {}


def _grant(**over):
    fields = {
        "expires_on": date(2027, 1, 1),
        "revoked": False,
        "booking_status": "confirmed",
        "booking_reference": "HTB-2026-0007",
    }
    fields.update(over)
    return Grant(**fields)


def test_a_live_link_opens():
    check_access(_grant(), today=TODAY)


def test_an_expired_link_says_when_and_that_nothing_has_changed():
    with pytest.raises(AccessRefused) as raised:
        check_access(_grant(expires_on=date(2026, 8, 1)), today=TODAY)
    assert raised.value.code == EXPIRED
    assert "01 August 2026" in raised.value.message
    assert "nothing about your booking has changed" in raised.value.message


def test_a_withdrawn_link_reassures_about_the_booking():
    with pytest.raises(AccessRefused) as raised:
        check_access(_grant(revoked=True), today=TODAY)
    assert raised.value.code == REVOKED
    assert "your booking is unaffected" in raised.value.message


def test_a_cancelled_booking_is_reported_as_cancelled():
    with pytest.raises(AccessRefused) as raised:
        check_access(
            _grant(booking_status="cancelled", expires_on=date(2026, 1, 1)),
            today=TODAY,
        )
    assert raised.value.code == CANCELLED
    assert "HTB-2026-0007" in raised.value.message
    assert "the record of it is not gone" in raised.value.message


def test_a_link_outlives_the_trip():
    assert default_expiry(
        date(2026, 11, 5), after_days=90, today=TODAY
    ) == date(2027, 2, 3)


def test_a_link_for_a_trip_already_past_is_not_dead_on_arrival():
    assert default_expiry(
        date(2026, 1, 5), after_days=90, today=TODAY, minimum_days=30
    ) == date(2026, 10, 4)
