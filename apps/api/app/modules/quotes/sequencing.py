from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import permutations

from app.modules.quotes.packages import Problem
from app.modules.quotes.routing import Road, plain

NO_ROAD = "sequence_road_not_on_file"
LONG_DRIVE = "sequence_drive_too_long"
SHORT_STAY = "sequence_stay_shorter_than_drive"
BETTER_ORDER = "sequence_shorter_order_exists"

MAX_LEGS_TO_REORDER = 7


@dataclass(frozen=True)
class Hop:

    from_place: str
    to_place: str
    road: Road | None = None
    nights_after: int = 0

    @property
    def minutes(self) -> int:
        return self.road.drive_time_minutes if self.road else 0

    @property
    def km(self) -> Decimal:
        return self.road.distance_km if self.road else Decimal(0)


@dataclass(frozen=True)
class Score:

    total_km: Decimal = Decimal(0)
    total_minutes: int = 0
    longest_minutes: int = 0
    unknown_hops: int = 0
    hops: int = 0

    @property
    def total_hours(self) -> Decimal:
        return (Decimal(self.total_minutes) / Decimal(60)).quantize(Decimal("0.1"))

    @property
    def is_complete(self) -> bool:
        return self.unknown_hops == 0


@dataclass
class Sequenced:

    hops: list[Hop] = field(default_factory=list)
    score: Score = field(default_factory=Score)
    problems: list[Problem] = field(default_factory=list)
    better_order: tuple[str, ...] = ()
    saving_km: Decimal = Decimal(0)


def hops_of(
    places: Sequence[str],
    *,
    road_for: Callable[[str, str], Road | None],
    nights: Sequence[int] | None = None,
) -> list[Hop]:
    out: list[Hop] = []
    stay = list(nights or [])
    for index in range(len(places) - 1):
        here, there = places[index], places[index + 1]
        if here == there:
            continue
        out.append(
            Hop(
                from_place=here,
                to_place=there,
                road=road_for(here, there),
                nights_after=(
                    stay[index + 1] if index + 1 < len(stay) else 0
                ),
            )
        )
    return out


def score(hops: Sequence[Hop]) -> Score:
    known = [hop for hop in hops if hop.road is not None]
    return Score(
        total_km=sum((hop.km for hop in known), Decimal(0)),
        total_minutes=sum(hop.minutes for hop in known),
        longest_minutes=max((hop.minutes for hop in known), default=0),
        unknown_hops=sum(1 for hop in hops if hop.road is None),
        hops=len(hops),
    )


def order_km(
    places: Sequence[str], *, road_for: Callable[[str, str], Road | None]
) -> Decimal | None:
    total = Decimal(0)
    for index in range(len(places) - 1):
        here, there = places[index], places[index + 1]
        if here == there:
            continue
        road = road_for(here, there)
        if road is None:
            return None
        total += road.distance_km
    return total


def shortest_order(
    places: Sequence[str], *, road_for: Callable[[str, str], Road | None]
) -> tuple[tuple[str, ...], Decimal] | None:
    if len(places) < 4 or len(places) > MAX_LEGS_TO_REORDER:
        return None
    first, last = places[0], places[-1]
    middle = list(places[1:-1])
    best: tuple[tuple[str, ...], Decimal] | None = None
    for candidate in permutations(middle):
        ordering = (first, *candidate, last)
        total = order_km(ordering, road_for=road_for)
        if total is None:
            return None
        if best is None or total < best[1]:
            best = (ordering, total)
    return best


def sequence(
    places: Sequence[str],
    *,
    road_for: Callable[[str, str], Road | None],
    nights: Sequence[int] | None = None,
    max_drive_minutes: int = 600,
) -> Sequenced:
    hops = hops_of(places, road_for=road_for, nights=nights)
    out = Sequenced(hops=hops, score=score(hops))

    for hop in hops:
        if hop.road is None:
            out.problems.append(
                Problem(
                    NO_ROAD,
                    f"No route is on file between {hop.from_place} and "
                    f"{hop.to_place}, so this itinerary's driving cannot be "
                    f"totalled and that drive cannot be costed. Enter the "
                    f"route.",
                    blocking=False,
                )
            )
            continue
        if hop.minutes > max_drive_minutes:
            hours = (Decimal(hop.minutes) / Decimal(60)).quantize(Decimal("0.1"))
            out.problems.append(
                Problem(
                    LONG_DRIVE,
                    f"{hop.from_place} to {hop.to_place} is about {hours} hours "
                    f"of driving, past the {max_drive_minutes // 60}-hour day "
                    f"this operation sells. Check the arrival is before the "
                    f"gate closes, or break the drive.",
                    blocking=False,
                )
            )
        if hop.nights_after == 1 and hop.minutes >= max_drive_minutes // 2:
            hours = (Decimal(hop.minutes) / Decimal(60)).quantize(Decimal("0.1"))
            out.problems.append(
                Problem(
                    SHORT_STAY,
                    f"{hop.to_place} is one night after about {hours} hours of "
                    f"driving. Most of two days on the road for one evening "
                    f"there — worth confirming the client wants it that way.",
                    blocking=False,
                )
            )

    given = order_km(places, road_for=road_for)
    best = shortest_order(places, road_for=road_for)
    if given is not None and best is not None and best[1] < given:
        out.better_order = best[0]
        out.saving_km = given - best[1]
        out.problems.append(
            Problem(
                BETTER_ORDER,
                f"Visiting {' → '.join(best[0])} instead drives "
                f"{plain(out.saving_km)} km less. That may be deliberate — a flight "
                f"time, a lodge's availability, a migration crossing — so it is "
                f"a note and not a correction.",
                blocking=False,
            )
        )
    return out
