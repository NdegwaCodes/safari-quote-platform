from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.modules.quotes.packages import Leg, Problem, order

NO_DAYS = "itinerary_no_days"
ACTIVITY_OFF_TRIP = "itinerary_activity_off_trip"
ACTIVITY_UNSCHEDULED = "itinerary_activity_unscheduled"
MOVEMENT_OFF_TRIP = "itinerary_movement_off_trip"
MOVEMENT_UNDATED = "itinerary_movement_undated"


@dataclass(frozen=True)
class Movement:

    sequence: int
    kind: str
    mode: str
    label: str
    on: date | None = None
    is_optional: bool = False
    duration_minutes: int | None = None


@dataclass(frozen=True)
class Excursion:

    name: str
    day: int | None = None
    is_mandatory: bool = True


@dataclass(frozen=True)
class Day:

    number: int
    on: date
    destination: str = ""
    property_name: str = ""
    board: str = ""
    leg: int | None = None
    moves_from: str = ""
    movements: tuple[Movement, ...] = ()
    excursions: tuple[str, ...] = ()
    is_arrival: bool = False
    is_departure: bool = False

    @property
    def has_night(self) -> bool:
        return not self.is_departure


def dates(*, arrival: date, departure: date) -> list[date]:
    span = (departure - arrival).days
    if span < 0:
        return []
    return [arrival + timedelta(days=n) for n in range(span + 1)]


def build(
    legs: list[Leg],
    *,
    arrival: date,
    departure: date,
    movements: list[Movement] | None = None,
    excursions: list[Excursion] | None = None,
) -> list[Day]:
    calendar = dates(arrival=arrival, departure=departure)
    if not calendar:
        return []

    ordered = order(legs)
    per_day_movements: dict[date, list[Movement]] = {}
    for movement in sorted(movements or [], key=lambda one: one.sequence):
        if movement.on is None:
            continue
        per_day_movements.setdefault(movement.on, []).append(movement)

    per_day_excursions: dict[int, list[str]] = {}
    for excursion in excursions or []:
        if excursion.day is None:
            continue
        per_day_excursions.setdefault(excursion.day, []).append(excursion.name)

    out: list[Day] = []
    previous: Leg | None = None
    for index, when in enumerate(calendar, start=1):
        holding = next(
            (leg for leg in ordered if leg.check_in <= when < leg.check_out), None
        )
        is_departure = when == departure
        if holding is None and is_departure and ordered:
            holding = ordered[-1]
        moved = (
            previous.property_name
            if previous is not None
            and holding is not None
            and previous.sequence != holding.sequence
            else ""
        )
        if holding is not None:
            previous = holding
        out.append(
            Day(
                number=index,
                on=when,
                destination=holding.destination if holding else "",
                property_name=holding.property_name if holding else "",
                board="" if is_departure or holding is None else holding.board,
                leg=holding.sequence if holding else None,
                moves_from=moved,
                movements=tuple(per_day_movements.get(when, ())),
                excursions=tuple(per_day_excursions.get(index, ())),
                is_arrival=when == arrival,
                is_departure=is_departure,
            )
        )
    return out


def check(
    *,
    arrival: date,
    departure: date,
    movements: list[Movement] | None = None,
    excursions: list[Excursion] | None = None,
) -> list[Problem]:
    problems: list[Problem] = []
    calendar = dates(arrival=arrival, departure=departure)
    if not calendar:
        return [
            Problem(
                NO_DAYS,
                f"The group departs on {departure}, which is not after the "
                f"arrival on {arrival}, so the trip has no days.",
            )
        ]

    total = len(calendar)
    for excursion in excursions or []:
        if excursion.day is None:
            problems.append(
                Problem(
                    ACTIVITY_UNSCHEDULED,
                    f"{excursion.name} is on the quote with no day, so it is "
                    f"charged but does not appear on the day-by-day. Set the "
                    f"day it falls on.",
                    blocking=False,
                )
            )
            continue
        if not 1 <= excursion.day <= total:
            problems.append(
                Problem(
                    ACTIVITY_OFF_TRIP,
                    f"{excursion.name} is scheduled for day {excursion.day}, "
                    f"but this trip is {total} day(s) long. Its fare is being "
                    f"selected for a date the group is not here.",
                )
            )

    for movement in sorted(movements or [], key=lambda one: one.sequence):
        if movement.on is None:
            problems.append(
                Problem(
                    MOVEMENT_UNDATED,
                    f"{movement.label or movement.mode} has no travel date, so "
                    f"it is priced at the arrival date's tariff and does not "
                    f"appear on the day-by-day. Set the day it runs.",
                    sequence=movement.sequence,
                    blocking=False,
                )
            )
            continue
        if not arrival <= movement.on <= departure:
            problems.append(
                Problem(
                    MOVEMENT_OFF_TRIP,
                    f"{movement.label or movement.mode} is dated "
                    f"{movement.on}, outside the {arrival} to {departure} "
                    f"trip, so it prices off the wrong tariff window.",
                    sequence=movement.sequence,
                )
            )

    return problems


@dataclass
class Programme:

    days: list[Day] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def programme(
    legs: list[Leg],
    *,
    arrival: date,
    departure: date,
    movements: list[Movement] | None = None,
    excursions: list[Excursion] | None = None,
) -> Programme:
    return Programme(
        days=build(
            legs,
            arrival=arrival,
            departure=departure,
            movements=movements,
            excursions=excursions,
        ),
        problems=check(
            arrival=arrival,
            departure=departure,
            movements=movements,
            excursions=excursions,
        ),
    )
