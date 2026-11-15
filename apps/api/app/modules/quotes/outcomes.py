from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

DRAFT = "draft"
SENT = "sent"
ACCEPTED = "accepted"
DECLINED = "declined"
EXPIRED = "expired"

OUTCOMES = (ACCEPTED, DECLINED)

TERMINAL = (ACCEPTED, DECLINED)


class OutcomeRefused(ValueError):
    pass


def effective_status(
    status: str, valid_until: date | None, *, today: date
) -> str:
    if status != SENT or valid_until is None:
        return status
    return EXPIRED if valid_until < today else SENT


def check_outcome(
    status: str, valid_until: date | None, *, outcome: str, today: date
) -> None:
    if outcome not in OUTCOMES:
        raise OutcomeRefused(
            f"'{outcome}' is not an outcome anybody records. A quote is "
            f"accepted or declined; expiry is a date, not a decision."
        )
    if status == DRAFT:
        raise OutcomeRefused(
            "This quote is still a draft, so nothing has been in front of the "
            "client to accept or decline. Issue it first."
        )
    if status in TERMINAL:
        raise OutcomeRefused(
            f"This quote was already {status}. Recording a second outcome "
            f"would overwrite what the client actually decided — raise a new "
            f"quote instead, which keeps both."
        )
    if effective_status(status, valid_until, today=today) == EXPIRED:
        if outcome == ACCEPTED:
            raise OutcomeRefused(
                f"This quote expired on {valid_until}. Accepting it would book "
                f"the trip at rates that have since moved — re-issue it, which "
                f"appends a version at today's prices, and accept that."
            )


@dataclass(frozen=True)
class Decided:

    status: str
    currency: str
    value: Decimal | None = None
    valid_until: date | None = None
    issued_on: date | None = None
    decided_on: date | None = None
    took_recommendation: bool | None = None


@dataclass
class Conversion:

    counts: dict[str, int] = field(default_factory=dict)
    won: dict[str, Decimal] = field(default_factory=dict)
    lost: dict[str, Decimal] = field(default_factory=dict)
    outstanding: dict[str, Decimal] = field(default_factory=dict)
    win_rate: Decimal | None = None
    median_days_to_decide: int | None = None
    recommendation_taken: int = 0
    recommendation_declined: int = 0

    @property
    def recommendation_rate(self) -> Decimal | None:
        total = self.recommendation_taken + self.recommendation_declined
        if not total:
            return None
        return (
            Decimal(self.recommendation_taken) / Decimal(total)
        ).quantize(Decimal("0.0001"))


def _add(bucket: dict[str, Decimal], currency: str, amount: Decimal | None) -> None:
    if amount is None:
        return
    bucket[currency] = bucket.get(currency, Decimal(0)) + amount


def convert(quotes: Iterable[Decided], *, today: date) -> Conversion:
    out = Conversion()
    gaps: list[int] = []
    for quote in quotes:
        status = effective_status(quote.status, quote.valid_until, today=today)
        out.counts[status] = out.counts.get(status, 0) + 1
        currency = quote.currency.upper()
        if status == ACCEPTED:
            _add(out.won, currency, quote.value)
        elif status == DECLINED:
            _add(out.lost, currency, quote.value)
        elif status in (SENT, EXPIRED):
            _add(out.outstanding, currency, quote.value)

        if (
            status in TERMINAL
            and quote.issued_on is not None
            and quote.decided_on is not None
        ):
            gaps.append((quote.decided_on - quote.issued_on).days)

        if status == ACCEPTED and quote.took_recommendation is not None:
            if quote.took_recommendation:
                out.recommendation_taken += 1
            else:
                out.recommendation_declined += 1

    decided = out.counts.get(ACCEPTED, 0) + out.counts.get(DECLINED, 0)
    if decided:
        out.win_rate = (
            Decimal(out.counts.get(ACCEPTED, 0)) / Decimal(decided)
        ).quantize(Decimal("0.0001"))
    if gaps:
        out.median_days_to_decide = median(gaps)
    return out


def median(values: Sequence[int]) -> int:
    if not values:
        raise ValueError("no values to take a median of")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2
