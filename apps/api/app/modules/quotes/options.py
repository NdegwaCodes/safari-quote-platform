from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import TypeVar

MEAL_PLAN_FALLBACK: dict[str, tuple[str, ...]] = {
    "FB": ("FB", "HB", "BB", "AI"),
    "HB": ("HB", "FB", "BB", "AI"),
    "BB": ("BB", "HB", "FB", "AI"),
    "AI": ("AI", "FB", "HB", "BB"),
    "RO": ("RO", "BB", "HB", "FB", "AI"),
}

PLANS_WITH_MEALS = frozenset({"FB", "AI"})

MEAL_GAPS: dict[str, int] = {"BB": 2, "RO": 3}

_R = TypeVar("_R")


def stay_nights(arrival: date, departure: date) -> list[date]:
    if departure <= arrival:
        raise ValueError("departure must be after arrival")
    span = (departure - arrival).days
    return [arrival + timedelta(days=offset) for offset in range(span)]


def rooms_required(pax: int, capacity: int) -> int:
    if pax <= 0:
        raise ValueError("pax must be at least 1")
    if capacity <= 0:
        raise ValueError("room capacity must be at least 1")
    return -(-pax // capacity)


def room_plan(pax: int, capacity: int) -> list[int]:
    count = rooms_required(pax, capacity)
    full, remainder = divmod(pax, capacity)
    plan = [capacity] * full
    if remainder:
        plan.append(remainder)
    assert len(plan) == count, (plan, count)
    return plan


def rate_for_occupancy(
    rates: dict[int, _R], occupancy: int
) -> tuple[int, _R] | None:
    if occupancy <= 0:
        raise ValueError("occupancy must be at least 1")
    if occupancy in rates:
        return occupancy, rates[occupancy]
    larger = sorted(key for key in rates if key > occupancy)
    if larger:
        return larger[0], rates[larger[0]]
    return None


def meal_plan_chain(requested: str) -> tuple[str, ...]:
    return MEAL_PLAN_FALLBACK.get(requested.upper(), (requested.upper(),))


def resolve_meal_plan(requested: str, available: set[str]) -> tuple[str | None, bool]:
    wanted = requested.upper()
    for candidate in meal_plan_chain(wanted):
        if candidate in available:
            return candidate, candidate != wanted
    return None, False


def needs_chef(plan: str) -> bool:
    return plan.upper() not in PLANS_WITH_MEALS and plan.upper() != "HB"


def meals_needing_chef(plan: str, nights: int) -> int:
    if nights < 0:
        raise ValueError("nights cannot be negative")
    return MEAL_GAPS.get(plan.upper(), 0) * nights


def default_chef_fee_per_meal(
    pax: int, plan: str, *, per_day: Decimal, covers: int
) -> Decimal | None:
    gap = MEAL_GAPS.get(plan.upper(), 0)
    if not gap:
        return None
    chefs = rooms_required(pax, covers)
    return (Decimal(chefs) * per_day) / gap


def supplier_paid(rate: Decimal, discount_pct: Decimal | None) -> Decimal:
    if discount_pct is None or discount_pct == 0:
        return rate
    return rate * (Decimal(1) - discount_pct / Decimal(100))


def costed_rate(rate: Decimal, discount_pct: Decimal | None, rate_kind: str) -> Decimal:
    if rate_kind == "sto":
        return supplier_paid(rate, discount_pct)
    if discount_pct is None or discount_pct == 0:
        return rate
    return rate * (Decimal(1) - (discount_pct / Decimal(2)) / Decimal(100))


def retained_discount(
    rate: Decimal, discount_pct: Decimal | None, rate_kind: str, *, units: int = 1
) -> Decimal:
    paid = supplier_paid(rate, discount_pct)
    costed = costed_rate(rate, discount_pct, rate_kind)
    return (costed - paid) * units


def nights_within(
    stay_start: date, stay_end: date, window_start: date, window_end: date
) -> int:
    first = max(stay_start, window_start)
    last = min(stay_end, window_end + _ONE_DAY)
    return max(0, (last - first).days)


_ONE_DAY = date(2000, 1, 2) - date(2000, 1, 1)


def supplement_cost(
    *,
    amount: Decimal,
    basis: str,
    pax: int,
    rooms: int,
    nights: int,
) -> Decimal:
    if nights <= 0:
        return Decimal(0)
    if basis == "per_person_per_night":
        return amount * pax * nights
    if basis == "per_person":
        return amount * pax
    if basis == "per_room_per_night":
        return amount * rooms * nights
    if basis == "per_room":
        return amount * rooms
    raise ValueError(f"unknown supplement basis: {basis!r}")


def meets_minimum_stay(nights: int, min_nights: int | None) -> bool:
    return min_nights is None or nights >= min_nights


def minimum_stay_reason(nights: int, min_nights: int) -> str:
    plural = "night" if min_nights == 1 else "nights"
    return (
        f"Requires a minimum stay of {min_nights} {plural}; "
        f"this itinerary is {nights} {'night' if nights == 1 else 'nights'}."
    )


def uniform_group(traveller_types: list[str]) -> bool:
    return len(set(traveller_types)) <= 1


def round_up_to(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("rounding step must be positive")
    return (value / step).quantize(Decimal(1), rounding=ROUND_CEILING) * step


@dataclass(frozen=True)
class BuildUp:

    cost_subtotal: Decimal
    contingency_value: Decimal
    cost_basis: Decimal
    profit_value: Decimal
    after_profit: Decimal
    agent_cover_fee: Decimal
    selling_total: Decimal
    per_person: Decimal | None
    group_total: Decimal
    components: dict[str, Decimal] = field(default_factory=dict)


def build_up(
    *,
    components: dict[str, Decimal],
    pax: int,
    contingency_pct: Decimal,
    profit_pct: Decimal,
    agent_cover_fee: Decimal = Decimal(0),
    rounding_step: Decimal = Decimal("100"),
    uniform_group: bool = True,
) -> BuildUp:
    if pax <= 0:
        raise ValueError("pax must be at least 1")
    for name, value in components.items():
        if value < 0:
            raise ValueError(f"cost component {name!r} is negative")
    if agent_cover_fee < 0:
        raise ValueError("agent cover fee cannot be negative")

    cost_subtotal = sum(components.values(), Decimal(0))
    contingency_value = cost_subtotal * contingency_pct / Decimal(100)
    cost_basis = cost_subtotal + contingency_value
    profit_value = cost_basis * profit_pct / Decimal(100)
    after_profit = cost_basis + profit_value
    selling_total = after_profit + agent_cover_fee

    if uniform_group:
        per_person = round_up_to(selling_total / pax, rounding_step)
        group_total = per_person * pax
    else:
        per_person = None
        group_total = round_up_to(selling_total, rounding_step)

    return BuildUp(
        cost_subtotal=cost_subtotal,
        contingency_value=contingency_value,
        cost_basis=cost_basis,
        profit_value=profit_value,
        after_profit=after_profit,
        agent_cover_fee=agent_cover_fee,
        selling_total=selling_total,
        per_person=per_person,
        group_total=group_total,
        components=dict(components),
    )
