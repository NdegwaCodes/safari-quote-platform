from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.modules.quotes.options import rate_for_occupancy, room_plan

TIER_BANDS: dict[str, tuple[int, int]] = {
    "comfort": (1, 3),
    "luxury": (4, 4),
    "ultra": (5, 5),
}

ROOM_CAPACITY = 2

NO_TIER = "estimate_unknown_tier"
NO_PROPERTY = "estimate_no_property"
NO_RATE = "estimate_no_rate"


class EstimateRefused(Exception):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def star_band(tier: str) -> tuple[int, int]:
    key = (tier or "").strip().lower()
    if key not in TIER_BANDS:
        raise EstimateRefused(
            NO_TIER,
            f"'{tier}' is not a comfort level we offer. Choose comfort, luxury "
            f"or ultra.",
        )
    return TIER_BANDS[key]


@dataclass(frozen=True)
class LegPriced:

    destination: str
    tier: str
    nights: int
    property_name: str | None = None
    room_type: str | None = None
    meal_plan: str | None = None
    currency: str | None = None
    per_person: Decimal | None = None
    group_total: Decimal | None = None
    refused: EstimateRefused | None = None

    @property
    def ok(self) -> bool:
        return self.refused is None


def price_rooms(
    rates_by_occupancy: dict[int, Decimal], *, pax: int
) -> Decimal | None:
    total = Decimal(0)
    for headcount in room_plan(pax, ROOM_CAPACITY):
        found = rate_for_occupancy(rates_by_occupancy, headcount)
        if found is None:
            return None
        _, rate = found
        total += rate
    return total


@dataclass(frozen=True)
class Combined:

    currency: str | None
    per_person: Decimal | None
    group_total: Decimal | None
    mixed_currency: bool = False


def combine(legs: list[LegPriced]) -> Combined:
    priced = [leg for leg in legs if leg.ok]
    if not priced or len(priced) != len(legs):
        return Combined(currency=None, per_person=None, group_total=None)
    currencies = {leg.currency for leg in priced}
    if len(currencies) > 1:
        return Combined(
            currency=None, per_person=None, group_total=None, mixed_currency=True
        )
    currency = currencies.pop()
    per_person = sum((leg.per_person or Decimal(0) for leg in priced), Decimal(0))
    group_total = sum((leg.group_total or Decimal(0) for leg in priced), Decimal(0))
    return Combined(currency=currency, per_person=per_person, group_total=group_total)


__all__ = [
    "NO_PROPERTY",
    "NO_RATE",
    "NO_TIER",
    "ROOM_CAPACITY",
    "TIER_BANDS",
    "Combined",
    "EstimateRefused",
    "LegPriced",
    "combine",
    "price_rooms",
    "star_band",
]
