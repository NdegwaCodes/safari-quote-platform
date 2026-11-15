from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")

DEPOSIT = "Deposit"
BALANCE = "Balance"
FULL = "Full payment"


class ScheduleRefused(ValueError):
    pass


@dataclass(frozen=True)
class Instalment:

    label: str
    due_on: date
    amount: Decimal
    currency: str
    sort_order: int = 0


@dataclass
class Owed:

    total: Decimal = Decimal(0)
    paid: Decimal = Decimal(0)
    balance: Decimal = Decimal(0)
    overpaid: Decimal = Decimal(0)
    currency: str = ""
    overdue: list[Instalment] = field(default_factory=list)
    next_due: Instalment | None = None

    @property
    def is_settled(self) -> bool:
        return self.balance <= 0


def build(
    total: Decimal,
    currency: str,
    *,
    deposit_pct: Decimal,
    travel_from: date,
    balance_due_days_before: int,
    today: date,
) -> list[Instalment]:
    if total <= 0:
        raise ScheduleRefused(
            "A booking with nothing to pay has no schedule. Check the version's "
            "selling price before booking it."
        )
    if not 0 < deposit_pct <= 100:
        raise ScheduleRefused(
            f"A deposit of {deposit_pct}% is not a deposit. Set a percentage "
            f"above zero and no more than a hundred."
        )
    amount = total.quantize(CENTS, rounding=ROUND_HALF_UP)
    code = currency.upper()
    balance_on = travel_from - timedelta(days=max(0, balance_due_days_before))

    deposit = (amount * deposit_pct / Decimal(100)).quantize(
        CENTS, rounding=ROUND_HALF_UP
    )
    balance = amount - deposit

    if balance <= 0 or balance_on <= today:
        return [
            Instalment(
                label=FULL, due_on=today, amount=amount, currency=code, sort_order=1
            )
        ]
    return [
        Instalment(
            label=DEPOSIT, due_on=today, amount=deposit, currency=code, sort_order=1
        ),
        Instalment(
            label=BALANCE,
            due_on=balance_on,
            amount=balance,
            currency=code,
            sort_order=2,
        ),
    ]


def owed(
    instalments: Sequence[Instalment],
    payments: Iterable[Decimal],
    *,
    total: Decimal | None = None,
    currency: str = "",
    today: date,
) -> Owed:
    schedule = sorted(instalments, key=lambda one: (one.due_on, one.sort_order))
    billed = sum((one.amount for one in schedule), Decimal(0))
    expected = (total if total is not None else billed).quantize(CENTS)
    received = sum(
        (amount for amount in payments), Decimal(0)
    ).quantize(CENTS)

    out = Owed(
        total=expected,
        paid=received,
        balance=max(Decimal(0), expected - received),
        overpaid=max(Decimal(0), received - expected),
        currency=(currency or (schedule[0].currency if schedule else "")).upper(),
    )

    running = received
    for instalment in schedule:
        if running >= instalment.amount:
            running -= instalment.amount
            continue
        if out.next_due is None:
            out.next_due = instalment
        if instalment.due_on < today:
            out.overdue.append(instalment)
        running = Decimal(0)
    return out


def is_confirmable(
    schedule: Sequence[Instalment], payments: Iterable[Decimal]
) -> bool:
    if not schedule:
        return False
    first = min(schedule, key=lambda one: (one.due_on, one.sort_order))
    received = sum((amount for amount in payments), Decimal(0))
    return received >= first.amount
