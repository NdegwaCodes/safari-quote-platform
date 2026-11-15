from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.modules.operations.supply import (
    CANCELLED,
    CONFIRMED,
    NOT_CONFIRMED,
    NOT_REQUESTED,
    OVER_BUDGET,
    REQUESTED,
    TO_REQUEST,
    UNDER_BUDGET,
    UNSETTLED,
    Committed,
    SupplyRefused,
    check_invoices,
    check_supply,
    check_transition,
    exposure,
    normalise_status,
    unsettled,
)

D = Decimal
TODAY = date(2026, 9, 5)


def _item(**over):
    fields = {
        "supplier": "Reef House",
        "status": CONFIRMED,
        "expected": D("180000"),
        "invoiced": None,
        "settled": None,
        "currency": "KES",
        "check_in": date(2026, 11, 2),
        "their_reference": "RH-88421",
    }
    fields.update(over)
    return Committed(**fields)


def test_a_status_is_refused_rather_than_defaulted():
    assert normalise_status("To Request") == TO_REQUEST
    with pytest.raises(SupplyRefused) as raised:
        normalise_status("pending")
    assert "not a state a supplier booking can be in" in str(raised.value)


def test_confirming_needs_their_reference():
    with pytest.raises(SupplyRefused) as raised:
        check_transition(REQUESTED, CONFIRMED)
    assert "needs the supplier's own reference" in str(raised.value)
    assert "stands in the lobby" in str(raised.value)
    check_transition(REQUESTED, CONFIRMED, their_reference="RH-88421")


def test_cancelling_needs_a_reason():
    with pytest.raises(SupplyRefused) as raised:
        check_transition(CONFIRMED, CANCELLED, reason="   ")
    assert "whether we moved the dates or they let us down" in str(raised.value)
    check_transition(CONFIRMED, CANCELLED, reason="Client moved the dates.")


def test_moving_to_where_it_already_is_is_refused():
    with pytest.raises(SupplyRefused) as raised:
        check_transition(CONFIRMED, CONFIRMED, their_reference="RH-1")
    assert "already confirmed" in str(raised.value)


def test_a_cancelled_reservation_is_asked_for_again_rather_than_revived():
    with pytest.raises(SupplyRefused) as raised:
        check_transition(CANCELLED, CONFIRMED, their_reference="RH-1")
    assert "Put it back to 'to request'" in str(raised.value)
    check_transition(CANCELLED, TO_REQUEST)


def test_a_request_can_go_straight_to_confirmed():
    check_transition(TO_REQUEST, CONFIRMED, their_reference="RH-88421")


def test_a_supplier_who_has_not_invoiced_is_not_owed_nothing():
    assert _item(invoiced=None).owed == D("180000")


def test_the_invoice_replaces_the_budget_once_it_arrives():
    assert _item(invoiced=D("195000")).owed == D("195000")


def test_what_has_been_paid_comes_off():
    assert _item(invoiced=D("195000"), settled=D("100000")).owed == D("95000")


def test_an_overpaid_supplier_is_owed_zero_and_never_less():
    assert _item(invoiced=D("180000"), settled=D("200000")).owed == D("0")


def test_a_cancelled_commitment_owes_nobody_anything():
    assert _item(status=CANCELLED, expected=D("180000")).owed == D("0")


def test_exposure_keeps_the_currencies_apart():
    found = exposure(
        [
            _item(currency="KES", expected=D("180000")),
            _item(supplier="Airport Transfers", currency="USD", expected=D("400")),
        ]
    )
    assert found.expected == {"KES": D("180000"), "USD": D("400")}
    assert found.owed == {"KES": D("180000"), "USD": D("400")}
    assert found.suppliers == 2
    assert found.all_confirmed is True


def test_exposure_counts_what_is_not_confirmed():
    found = exposure([_item(), _item(supplier="Park gate", status=REQUESTED)])
    assert found.unconfirmed == 1
    assert found.all_confirmed is False


def test_a_cancelled_commitment_is_not_counted_at_all():
    found = exposure([_item(status=CANCELLED)])
    assert found.suppliers == 0
    assert found.expected == {}
    assert found.all_confirmed is False


def test_a_supplier_nobody_has_asked_is_reported_near_departure():
    found = check_supply(
        [_item(status=TO_REQUEST)],
        departs_on=date(2026, 9, 12),
        today=TODAY,
        confirm_by_days=14,
    )
    concern = next(one for one in found if one.code == NOT_REQUESTED)
    assert "has not been asked yet" in concern.message
    assert "leaves in 7 day(s)" in concern.message
    assert concern.supplier == "Reef House"


def test_an_unanswered_request_is_not_a_reservation():
    found = check_supply(
        [_item(status=REQUESTED)], departs_on=date(2026, 9, 12), today=TODAY
    )
    concern = next(one for one in found if one.code == NOT_CONFIRMED)
    assert "an unanswered request is not a reservation" in concern.message


def test_a_confirmed_supplier_is_not_on_the_board():
    assert (
        check_supply([_item()], departs_on=date(2026, 9, 12), today=TODAY) == []
    )


def test_the_threshold_is_the_callers():
    far = [_item(status=TO_REQUEST)]
    assert check_supply(far, departs_on=date(2026, 12, 1), today=TODAY) == []
    assert (
        check_supply(
            far, departs_on=date(2026, 12, 1), today=TODAY, confirm_by_days=120
        )
        != []
    )


def test_a_per_row_deadline_overrides_the_threshold():
    found = check_supply(
        [_item(status=TO_REQUEST, confirm_by=date(2026, 9, 1))],
        departs_on=date(2027, 3, 1),
        today=TODAY,
    )
    assert [one.code for one in found] == [NOT_REQUESTED]


def test_a_cancelled_commitment_is_not_chased():
    assert (
        check_supply(
            [_item(status=CANCELLED)], departs_on=date(2026, 9, 12), today=TODAY
        )
        == []
    )


def test_a_supplier_billing_over_budget_says_it_comes_out_of_the_margin():
    found = check_invoices([_item(invoiced=D("195000"))])
    concern = next(one for one in found if one.code == OVER_BUDGET)
    assert "invoiced 195000 KES against a budget of 180000" in concern.message
    assert "15000 more" in concern.message
    assert "straight out of the margin" in concern.message
    assert concern.variance_pct == D("8.33")


def test_under_billing_is_not_reported_as_good_news():
    found = check_invoices([_item(invoiced=D("165000"))])
    concern = next(one for one in found if one.code == UNDER_BUDGET)
    assert "15000 less" in concern.message
    assert "left something off" in concern.message


def test_an_invoice_close_to_the_budget_is_left_alone():
    assert check_invoices([_item(invoiced=D("181000"))]) == []


def test_a_supplier_who_has_not_invoiced_is_not_a_variance():
    assert check_invoices([_item(invoiced=None)]) == []


def test_a_commitment_with_no_budget_is_not_a_variance():
    assert check_invoices([_item(expected=D("0"), invoiced=D("5000"))]) == []


def test_a_supplier_still_owed_after_the_group_left_is_reported():
    found = unsettled(
        [_item(invoiced=D("180000"))],
        departed_on=date(2026, 8, 29),
        today=TODAY,
    )
    concern = next(one for one in found if one.code == UNSETTLED)
    assert "still owed 180000 KES" in concern.message
    assert "7 day(s) after the group left" in concern.message


def test_a_trip_that_has_not_happened_yet_owes_nothing_late():
    assert (
        unsettled(
            [_item(invoiced=D("180000"))],
            departed_on=date(2026, 11, 5),
            today=TODAY,
        )
        == []
    )


def test_a_settled_supplier_is_not_reported():
    assert (
        unsettled(
            [_item(invoiced=D("180000"), settled=D("180000"))],
            departed_on=date(2026, 8, 29),
            today=TODAY,
        )
        == []
    )
