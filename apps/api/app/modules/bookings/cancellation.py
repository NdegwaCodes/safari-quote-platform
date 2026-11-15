from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

TIER_DEPOSIT_ONLY = "deposit_only"
TIER_SECOND = "second_tier"
TIER_THIRD = "third_tier"
TIER_FORFEIT = "forfeit"
TIER_PEAK = "peak_period"


@dataclass(frozen=True)
class PeakPeriod:

    start: date
    end: date
    label: str = ""

    def covers(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class Cancellation:

    notice_days: int
    band: str
    is_peak: bool
    is_group: bool
    retained_pct: Decimal
    retained_amount: Decimal
    peak_label: str = ""


def notice_days(*, departure_date: date, notice_on: date) -> int:
    return (departure_date - notice_on).days


def peak_period_covering(
    departure_date: date, periods: list[PeakPeriod]
) -> PeakPeriod | None:
    for period in periods:
        if period.covers(departure_date):
            return period
    return None


def check_cancellation(
    *,
    total_amount: Decimal,
    departure_date: date,
    notice_on: date,
    pax_count: int,
    is_exclusive_use: bool,
    deposit_pct: Decimal,
    tier1_days: int,
    tier2_days: int,
    tier2_pct: Decimal,
    tier3_days: int,
    tier3_pct: Decimal,
    forfeit_pct: Decimal,
    group_pax_threshold: int,
    group_notice_extension_days: int,
    peak_periods: list[PeakPeriod] | None = None,
) -> Cancellation:
    if total_amount < 0:
        raise ValueError("total_amount cannot be negative")
    tiers = (("tier1_days", tier1_days), ("tier2_days", tier2_days), ("tier3_days", tier3_days))
    for name, days in tiers:
        if days < 0:
            raise ValueError(f"{name} cannot be negative")

    days = notice_days(departure_date=departure_date, notice_on=notice_on)
    is_group = pax_count >= group_pax_threshold or is_exclusive_use
    extension = group_notice_extension_days if is_group else 0

    peak = peak_period_covering(departure_date, peak_periods or [])
    if peak is not None:
        band, pct = TIER_PEAK, forfeit_pct
    elif days >= tier1_days + extension:
        band, pct = TIER_DEPOSIT_ONLY, deposit_pct
    elif days >= tier2_days + extension:
        band, pct = TIER_SECOND, tier2_pct
    elif days >= tier3_days + extension:
        band, pct = TIER_THIRD, tier3_pct
    else:
        band, pct = TIER_FORFEIT, forfeit_pct

    retained = (total_amount * pct / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return Cancellation(
        notice_days=days,
        band=band,
        is_peak=peak is not None,
        is_group=is_group,
        retained_pct=pct,
        retained_amount=retained,
        peak_label=peak.label if peak else "",
    )


@dataclass(frozen=True)
class Settlement:

    retained_amount: Decimal
    paid_amount: Decimal
    refund_due: Decimal
    still_owed: Decimal


def settle_cancellation(
    *, retained_amount: Decimal, paid_amount: Decimal
) -> Settlement:
    if retained_amount < 0:
        raise ValueError("retained_amount cannot be negative")
    if paid_amount < 0:
        raise ValueError("paid_amount cannot be negative")
    return Settlement(
        retained_amount=retained_amount,
        paid_amount=paid_amount,
        refund_due=max(paid_amount - retained_amount, Decimal(0)),
        still_owed=max(retained_amount - paid_amount, Decimal(0)),
    )


__all__ = [
    "TIER_DEPOSIT_ONLY",
    "TIER_FORFEIT",
    "TIER_PEAK",
    "TIER_SECOND",
    "TIER_THIRD",
    "Cancellation",
    "PeakPeriod",
    "Settlement",
    "check_cancellation",
    "notice_days",
    "peak_period_covering",
    "settle_cancellation",
]
