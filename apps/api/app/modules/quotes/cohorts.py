from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from app.modules.quotes.options import BuildUp, build_up, room_plan, rooms_required

BASES: frozenset[str] = frozenset(
    {
        "per_person_per_night",
        "per_person_per_day",
        "per_person",
        "per_room_per_night",
        "per_room",
        "per_group_per_night",
        "per_group_per_day",
        "per_group",
    }
)


def multiplier(
    basis: str, *, pax: int, nights: int, days: int, rooms: int, units: int = 1
) -> int:
    if basis not in BASES:
        raise ValueError(f"unknown cost basis: {basis!r}")
    if units < 0:
        raise ValueError("units cannot be negative")
    per = {
        "per_person_per_night": pax * nights,
        "per_person_per_day": pax * days,
        "per_person": pax,
        "per_room_per_night": rooms * nights,
        "per_room": rooms,
        "per_group_per_night": nights,
        "per_group_per_day": days,
        "per_group": 1,
    }[basis]
    return max(0, per) * units


MICE_LADDER: tuple[tuple[int, int, Decimal], ...] = (
    (10, 29, Decimal("5")),
    (30, 49, Decimal("10")),
    (50, 99, Decimal("20")),
    (100, 10_000_000, Decimal("30")),
)


def mice_discount_pct(
    pax: int, *, ladder: Sequence[tuple[int, int, Decimal]] | None = None
) -> Decimal:
    if not ladder:
        return Decimal(0)
    for low, high, pct in ladder:
        if low <= pax <= high:
            return pct
    return Decimal(0)


@dataclass(frozen=True)
class Cohort:

    residence: str
    traveller_type: str
    count: int
    currency: str

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValueError("a cohort with no travellers is not a cohort")
        if not self.residence or not self.traveller_type:
            raise ValueError("a cohort needs a residence and a traveller type")
        if len(self.currency) != 3:
            raise ValueError("currency must be a three-letter code")

    @property
    def key(self) -> str:
        return f"{self.residence}:{self.traveller_type}"


@dataclass(frozen=True)
class Group:

    cohorts: tuple[Cohort, ...]

    def __post_init__(self) -> None:
        if not self.cohorts:
            raise ValueError("a quote needs at least one traveller")
        keys = [cohort.key for cohort in self.cohorts]
        if len(keys) != len(set(keys)):
            raise ValueError(f"duplicate cohort in group: {sorted(keys)}")
        for residence in self.residences:
            currencies = {
                cohort.currency for cohort in self.cohorts
                if cohort.residence == residence
            }
            if len(currencies) > 1:
                raise ValueError(
                    f"{residence} cohorts disagree on currency: {sorted(currencies)}"
                )

    @property
    def pax(self) -> int:
        return sum(cohort.count for cohort in self.cohorts)

    @property
    def residences(self) -> tuple[str, ...]:
        seen: list[str] = []
        for cohort in self.cohorts:
            if cohort.residence not in seen:
                seen.append(cohort.residence)
        return tuple(seen)

    @property
    def is_uniform(self) -> bool:
        return len(self.cohorts) == 1

    def currency_for(self, residence: str) -> str:
        for cohort in self.cohorts:
            if cohort.residence == residence:
                return cohort.currency
        raise KeyError(residence)

    def headcount(self, residence: str) -> int:
        return sum(
            cohort.count for cohort in self.cohorts if cohort.residence == residence
        )

    def cohorts_in(self, residence: str) -> tuple[Cohort, ...]:
        return tuple(
            cohort for cohort in self.cohorts if cohort.residence == residence
        )

    def count_of(self, residence: str, traveller_type: str) -> int:
        return sum(
            cohort.count
            for cohort in self.cohorts
            if cohort.residence == residence
            and cohort.traveller_type == traveller_type
        )


    def rooming(
        self, capacity: int, *, occupants: dict[str, int] | None = None
    ) -> dict[str, list[int]]:
        override = occupants or {}
        return {
            residence: room_plan(
                override.get(residence, self.headcount(residence)), capacity
            )
            for residence in self.residences
        }

    def rooms_for(self, residence: str, capacity: int) -> int:
        return rooms_required(self.headcount(residence), capacity)

    def total_rooms(self, capacity: int) -> int:
        return sum(
            self.rooms_for(residence, capacity) for residence in self.residences
        )


def group_from_counts(
    counts: Iterable[tuple[str, str, int]], currencies: dict[str, str]
) -> Group:
    cohorts = tuple(
        Cohort(
            residence=residence,
            traveller_type=traveller_type,
            count=count,
            currency=currencies[residence],
        )
        for residence, traveller_type, count in counts
        if count > 0
    )
    return Group(cohorts=cohorts)


@dataclass(frozen=True)
class CostLine:

    label: str
    amount: Decimal
    currency: str
    basis: str
    residence: str | None = None
    traveller_type: str | None = None
    bearers: tuple[str, ...] = ()
    nights: int = 0
    days: int = 0
    rooms: int = 0
    units: int = 1

    def __post_init__(self) -> None:
        if self.basis not in BASES:
            raise ValueError(f"unknown cost basis: {self.basis!r}")
        if self.amount < 0:
            raise ValueError(f"cost line {self.label!r} is negative")
        if self.bearers and self.traveller_type is not None:
            raise ValueError(
                f"cost line {self.label!r} names both a traveller type and a set "
                "of bearers; one line belongs either to one cohort or to several"
            )
        if self.bearers and self.residence is None:
            raise ValueError(
                f"cost line {self.label!r} names bearers without a residence; "
                "a set of traveller types spanning two sheets is not one line"
            )
        if self.traveller_type is not None and self.residence is None:
            raise ValueError(
                f"cost line {self.label!r} names a traveller type without a "
                "residence; a child rate belongs to one residency's sheet"
            )

    def cost(self, *, pax: int, rooms: int) -> Decimal:
        return self.amount * multiplier(
            self.basis,
            pax=pax,
            nights=self.nights,
            days=self.days,
            rooms=rooms,
            units=self.units,
        )


def _split_per_head(
    total: Decimal, cohorts: Sequence[Cohort]
) -> dict[str, Decimal]:
    if not cohorts:
        return {}
    heads = sum(cohort.count for cohort in cohorts)
    shares: dict[str, Decimal] = {}
    running = Decimal(0)
    for cohort in cohorts[:-1]:
        share = (total * cohort.count / heads).quantize(Decimal("0.0001"))
        shares[cohort.key] = share
        running += share
    shares[cohorts[-1].key] = total - running
    return shares


def attribute(
    lines: Iterable[CostLine],
    group: Group,
    *,
    capacity: int,
    convert: Callable[[Decimal, str, str], Decimal] | None = None,
) -> dict[str, dict[str, Decimal]]:
    per_cohort: dict[str, dict[str, Decimal]] = {
        cohort.key: {} for cohort in group.cohorts
    }

    for line in lines:
        if line.residence is not None and line.traveller_type is not None:
            targets = [
                cohort for cohort in group.cohorts
                if cohort.residence == line.residence
                and cohort.traveller_type == line.traveller_type
            ]
        elif line.residence is not None and line.bearers:
            targets = [
                cohort for cohort in group.cohorts_in(line.residence)
                if cohort.traveller_type in line.bearers
            ]
        elif line.residence is not None:
            targets = list(group.cohorts_in(line.residence))
        else:
            targets = list(group.cohorts)

        if not targets and line.bearers:
            raise ValueError(
                f"cost line {line.label!r} names bearers {sorted(line.bearers)} "
                f"but no {line.residence} cohort is one of them"
            )
        if not targets:
            continue

        expected = {cohort.currency for cohort in targets}
        if expected != {line.currency} and convert is None:
            raise ValueError(
                f"cost line {line.label!r} is in {line.currency} but its cohorts "
                f"are billed in {sorted(expected)}, and no converter was given"
            )

        if line.residence is not None:
            pax = sum(cohort.count for cohort in targets)
            rooms = group.rooms_for(line.residence, capacity)
        else:
            pax = group.pax
            rooms = group.total_rooms(capacity)

        total = line.cost(pax=pax, rooms=rooms)
        if total == 0:
            continue

        if len(targets) == 1:
            shares = {targets[0].key: total}
        else:
            shares = _split_per_head(total, targets)

        billed = {cohort.key: cohort.currency for cohort in targets}
        for key, share in shares.items():
            if billed[key] != line.currency:
                assert convert is not None
                share = convert(share, line.currency, billed[key])
            bucket = per_cohort[key]
            bucket[line.label] = bucket.get(line.label, Decimal(0)) + share

    return per_cohort


@dataclass(frozen=True)
class CohortPrice:

    cohort: Cohort
    build_up: BuildUp

    @property
    def per_person(self) -> Decimal:
        assert self.build_up.per_person is not None
        return self.build_up.per_person

    @property
    def total(self) -> Decimal:
        return self.build_up.group_total

    @property
    def currency(self) -> str:
        return self.cohort.currency


@dataclass(frozen=True)
class GroupPrice:

    cohorts: tuple[CohortPrice, ...]
    group_total: Decimal
    group_currency: str
    conversions: dict[str, Decimal] = field(default_factory=dict)

    @property
    def pax(self) -> int:
        return sum(price.cohort.count for price in self.cohorts)

    def per_person(self, residence: str, traveller_type: str = "adult") -> Decimal:
        for price in self.cohorts:
            if (
                price.cohort.residence == residence
                and price.cohort.traveller_type == traveller_type
            ):
                return price.per_person
        raise KeyError(f"{residence}:{traveller_type}")


def price_group(
    *,
    lines: Iterable[CostLine],
    group: Group,
    capacity: int,
    contingency_pct: Decimal,
    profit_pct: Decimal,
    agent_cover_fee: Decimal = Decimal(0),
    rounding_step: Decimal | Callable[[str], Decimal] = Decimal("100"),
    group_currency: str,
    convert: Callable[[Decimal, str, str], Decimal] | None = None,
    rate_used: Callable[[str, str], Decimal] | None = None,
) -> GroupPrice:
    components = attribute(lines, group, capacity=capacity, convert=convert)
    fee_shares = _split_per_head(agent_cover_fee, group.cohorts) if agent_cover_fee else {}

    def step_for(currency: str) -> Decimal:
        return (
            rounding_step(currency) if callable(rounding_step) else rounding_step
        )

    priced: list[CohortPrice] = []
    for cohort in group.cohorts:
        priced.append(
            CohortPrice(
                cohort=cohort,
                build_up=build_up(
                    components=components[cohort.key],
                    pax=cohort.count,
                    contingency_pct=contingency_pct,
                    profit_pct=profit_pct,
                    agent_cover_fee=fee_shares.get(cohort.key, Decimal(0)),
                    rounding_step=step_for(cohort.currency),
                    uniform_group=True,
                ),
            )
        )

    total = Decimal(0)
    conversions: dict[str, Decimal] = {}
    for price in priced:
        if price.currency == group_currency:
            total += price.total
            continue
        if convert is None:
            raise ValueError(
                f"cohort billed in {price.currency} but no converter was given "
                f"to reach {group_currency}"
            )
        total += convert(price.total, price.currency, group_currency)
        if rate_used is not None:
            conversions[f"{price.currency}/{group_currency}"] = rate_used(
                price.currency, group_currency
            )

    return GroupPrice(
        cohorts=tuple(priced),
        group_total=total,
        group_currency=group_currency,
        conversions=conversions,
    )
