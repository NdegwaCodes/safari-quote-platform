from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.modules.bookings.schedule import (
    BALANCE,
    DEPOSIT,
    FULL,
    Instalment,
    ScheduleRefused,
    build,
    is_confirmable,
    owed,
)

D = Decimal
TODAY = date(2026, 9, 4)
NEXT_YEAR = date(2027, 7, 1)


def _build(total, *, deposit=D("30"), travel=NEXT_YEAR, days_before=30, today=TODAY):
    return build(
        D(total),
        "KES",
        deposit_pct=deposit,
        travel_from=travel,
        balance_due_days_before=days_before,
        today=today,
    )


def test_a_deposit_and_a_balance_on_their_own_dates():
    schedule = _build("400000")
    assert [one.label for one in schedule] == [DEPOSIT, BALANCE]
    assert schedule[0].amount == D("120000.00")
    assert schedule[0].due_on == TODAY
    assert schedule[1].amount == D("280000.00")
    assert schedule[1].due_on == date(2027, 6, 1)
    assert all(one.currency == "KES" for one in schedule)


def test_the_instalments_add_up_to_the_total_exactly():
    for total in ("223749", "223749.01", "0.03", "999999.99", "7", "1234.56"):
        schedule = _build(total)
        assert sum(one.amount for one in schedule) == D(total).quantize(D("0.01")), total


def test_odd_percentages_still_add_up():
    for pct in ("1", "7.5", "33.333", "49.99", "99"):
        schedule = _build("223749", deposit=D(pct))
        assert sum(one.amount for one in schedule) == D("223749.00"), pct


def test_a_full_deposit_is_one_payment():
    schedule = _build("400000", deposit=D("100"))
    assert [one.label for one in schedule] == [FULL]
    assert schedule[0].amount == D("400000.00")


def test_a_late_booking_is_one_payment_due_now():
    schedule = _build("400000", travel=TODAY + timedelta(days=10))
    assert [one.label for one in schedule] == [FULL]
    assert schedule[0].due_on == TODAY
    assert schedule[0].amount == D("400000.00")


def test_a_booking_exactly_on_the_balance_date_is_one_payment():
    schedule = _build("400000", travel=TODAY + timedelta(days=30))
    assert [one.label for one in schedule] == [FULL]


def test_a_booking_one_day_clear_of_it_is_two():
    schedule = _build("400000", travel=TODAY + timedelta(days=31))
    assert [one.label for one in schedule] == [DEPOSIT, BALANCE]
    assert schedule[1].due_on == TODAY + timedelta(days=1)


def test_a_booking_with_nothing_to_pay_is_refused():
    with pytest.raises(ScheduleRefused, match="nothing to pay"):
        _build("0")
    with pytest.raises(ScheduleRefused):
        _build("-100")


def test_an_impossible_deposit_is_refused():
    with pytest.raises(ScheduleRefused, match="is not a deposit"):
        _build("400000", deposit=D("0"))
    with pytest.raises(ScheduleRefused):
        _build("400000", deposit=D("140"))


def test_the_currency_is_carried_onto_every_line():
    schedule = build(
        D("3200"),
        "usd",
        deposit_pct=D("50"),
        travel_from=NEXT_YEAR,
        balance_due_days_before=30,
        today=TODAY,
    )
    assert [one.currency for one in schedule] == ["USD", "USD"]


def _owed(paid, *, schedule=None, total="400000", today=TODAY):
    return owed(
        schedule if schedule is not None else _build(total),
        [D(one) for one in paid],
        total=D(total),
        currency="KES",
        today=today,
    )


def test_nothing_paid_owes_everything():
    position = _owed([])
    assert position.paid == D("0.00")
    assert position.balance == D("400000.00")
    assert not position.is_settled
    assert position.next_due is not None
    assert position.next_due.label == DEPOSIT


def test_the_deposit_paid_leaves_the_balance():
    position = _owed(["120000"])
    assert position.balance == D("280000.00")
    assert position.next_due.label == BALANCE
    assert position.overdue == []


def test_paid_in_full_is_settled():
    position = _owed(["120000", "280000"])
    assert position.balance == D("0.00")
    assert position.is_settled
    assert position.next_due is None


def test_an_overpayment_is_a_credit_and_not_a_negative_bill():
    position = _owed(["404000"])
    assert position.balance == D("0.00")
    assert position.overpaid == D("4000.00")
    assert position.is_settled


def test_a_part_payment_of_the_deposit_still_owes_the_deposit():
    position = _owed(["100000"])
    assert position.balance == D("300000.00")
    assert position.next_due.label == DEPOSIT


def test_one_payment_can_settle_two_instalments():
    position = _owed(["400000"])
    assert position.is_settled
    assert position.next_due is None


def test_an_overdue_instalment_is_reported_oldest_first():
    schedule = [
        Instalment(DEPOSIT, date(2026, 6, 1), D("120000"), "KES", 1),
        Instalment(BALANCE, date(2026, 8, 1), D("280000"), "KES", 2),
    ]
    position = _owed([], schedule=schedule)
    assert [one.label for one in position.overdue] == [DEPOSIT, BALANCE]
    assert position.next_due.label == DEPOSIT


def test_a_future_instalment_is_not_overdue():
    position = _owed(["120000"])
    assert position.overdue == []
    assert position.next_due.due_on > TODAY


def test_the_total_wins_over_the_schedule_when_they_disagree():
    schedule = [Instalment(DEPOSIT, TODAY, D("100000"), "KES", 1)]
    position = _owed([], schedule=schedule, total="400000")
    assert position.total == D("400000.00")
    assert position.balance == D("400000.00")


def test_a_booking_confirms_on_the_deposit_not_the_balance():
    schedule = _build("400000")
    assert not is_confirmable(schedule, [D("119999.99")])
    assert is_confirmable(schedule, [D("120000")])
    assert is_confirmable(schedule, [D("60000"), D("60000")])
    assert not is_confirmable([], [D("400000")])


def test_the_position_is_the_same_twice():
    schedule = _build("223749")
    first = owed(schedule, [D("60000")], total=D("223749"), currency="KES", today=TODAY)
    second = owed(schedule, [D("60000")], total=D("223749"), currency="KES", today=TODAY)
    assert first == second
