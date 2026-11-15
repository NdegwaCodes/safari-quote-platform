from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

NO_LEGS = "package_no_legs"
BAD_RANGE = "package_leg_dates_reversed"
GAP = "package_leg_gap"
OVERLAP = "package_leg_overlap"
LATE_START = "package_starts_after_arrival"
EARLY_START = "package_starts_before_arrival"
SHORT_END = "package_ends_before_departure"
LONG_END = "package_ends_after_departure"
DUPLICATE_SEQUENCE = "package_duplicate_sequence"
REPEATED_DESTINATION = "package_destination_repeated"
TOO_SHORT = "package_leg_below_minimum_stay"


@dataclass(frozen=True)
class Leg:

    sequence: int
    destination: str
    check_in: date
    check_out: date
    property_name: str = ""
    board: str = ""

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days


@dataclass(frozen=True)
class Problem:

    code: str
    message: str
    sequence: int | None = None
    blocking: bool = True


def order(legs: list[Leg]) -> list[Leg]:
    return sorted(legs, key=lambda leg: leg.sequence)


def total_nights(legs: list[Leg]) -> int:
    return sum(leg.nights for leg in legs)


def check(
    legs: list[Leg],
    *,
    arrival: date,
    departure: date,
    minimum_stay: dict[int, int] | None = None,
) -> list[Problem]:
    problems: list[Problem] = []
    if not legs:
        return [
            Problem(
                NO_LEGS,
                "This package has no legs, so there is nothing to price.",
                blocking=True,
            )
        ]

    ordered = order(legs)

    seen: dict[int, int] = {}
    for leg in ordered:
        seen[leg.sequence] = seen.get(leg.sequence, 0) + 1
    for sequence, count in sorted(seen.items()):
        if count > 1:
            problems.append(
                Problem(
                    DUPLICATE_SEQUENCE,
                    f"Two legs share position {sequence}, so the order of the "
                    f"itinerary is undefined.",
                    sequence=sequence,
                )
            )

    for leg in ordered:
        if leg.check_out <= leg.check_in:
            problems.append(
                Problem(
                    BAD_RANGE,
                    f"Leg {leg.sequence} ({leg.destination}) checks out on "
                    f"{leg.check_out}, which is not after its check-in of "
                    f"{leg.check_in}.",
                    sequence=leg.sequence,
                )
            )

    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if later.check_in > earlier.check_out:
            missing = (later.check_in - earlier.check_out).days
            problems.append(
                Problem(
                    GAP,
                    f"{missing} night(s) between leg {earlier.sequence} "
                    f"({earlier.destination}, out {earlier.check_out}) and leg "
                    f"{later.sequence} ({later.destination}, in "
                    f"{later.check_in}) have no accommodation.",
                    sequence=later.sequence,
                )
            )
        elif later.check_in < earlier.check_out:
            doubled = (earlier.check_out - later.check_in).days
            problems.append(
                Problem(
                    OVERLAP,
                    f"Leg {later.sequence} ({later.destination}) starts "
                    f"{doubled} night(s) before leg {earlier.sequence} "
                    f"({earlier.destination}) ends, so those nights are paid "
                    f"for in two places at once.",
                    sequence=later.sequence,
                )
            )

    first, last = ordered[0], ordered[-1]
    if first.check_in > arrival:
        problems.append(
            Problem(
                LATE_START,
                f"The package starts on {first.check_in} but the group arrives "
                f"on {arrival}, leaving "
                f"{(first.check_in - arrival).days} night(s) unaccounted for.",
                sequence=first.sequence,
            )
        )
    elif first.check_in < arrival:
        problems.append(
            Problem(
                EARLY_START,
                f"The package starts on {first.check_in}, before the group "
                f"arrives on {arrival}.",
                sequence=first.sequence,
            )
        )
    if last.check_out < departure:
        problems.append(
            Problem(
                SHORT_END,
                f"The package ends on {last.check_out} but the group departs on "
                f"{departure}, leaving "
                f"{(departure - last.check_out).days} night(s) unaccounted for.",
                sequence=last.sequence,
            )
        )
    elif last.check_out > departure:
        problems.append(
            Problem(
                LONG_END,
                f"The package ends on {last.check_out}, after the group departs "
                f"on {departure}.",
                sequence=last.sequence,
            )
        )

    for leg in ordered:
        needed = (minimum_stay or {}).get(leg.sequence)
        if needed and leg.nights < needed:
            problems.append(
                Problem(
                    TOO_SHORT,
                    f"Leg {leg.sequence} ({leg.property_name or leg.destination}) "
                    f"is {leg.nights} night(s) but the property requires "
                    f"{needed}.",
                    sequence=leg.sequence,
                )
            )

    counts: dict[str, list[int]] = {}
    for leg in ordered:
        counts.setdefault(leg.destination, []).append(leg.sequence)
    for destination, sequences in sorted(counts.items()):
        if len(sequences) > 1:
            problems.append(
                Problem(
                    REPEATED_DESTINATION,
                    f"{destination} appears on legs "
                    f"{', '.join(str(s) for s in sequences)}. That is normal for "
                    f"a city at both ends of a safari; check it is not a copied "
                    f"leg.",
                    sequence=sequences[-1],
                    blocking=False,
                )
            )

    return problems


def blocking(problems: list[Problem]) -> list[Problem]:
    return [problem for problem in problems if problem.blocking]


def nights_of(leg: Leg) -> list[date]:
    return [leg.check_in + timedelta(days=n) for n in range(leg.nights)]
