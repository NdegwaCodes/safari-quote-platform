from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

DRIVER = "driver"
GUIDE = "guide"
DRIVER_GUIDE = "driver_guide"
CREW_ROLES = (DRIVER, GUIDE, DRIVER_GUIDE)

DRIVES = (DRIVER, DRIVER_GUIDE)
GUIDES = (GUIDE, DRIVER_GUIDE)

NO_VEHICLE = "trip_no_vehicle"
NO_DRIVER = "trip_no_driver"
NOT_ENOUGH_SEATS = "trip_seats_short"
LICENCE_EXPIRING = "crew_licence_expires_during_trip"
TIGHT_TURNAROUND = "assignment_tight_turnaround"


class AssignmentRefused(ValueError):
    pass


@dataclass(frozen=True)
class Window:

    starts_on: date
    ends_on: date

    def __post_init__(self) -> None:
        if self.ends_on < self.starts_on:
            raise AssignmentRefused(
                "An assignment cannot end before it starts."
            )

    @property
    def days(self) -> int:
        return (self.ends_on - self.starts_on).days + 1

    def shared_days(self, other: Window) -> int:
        first = max(self.starts_on, other.starts_on)
        last = min(self.ends_on, other.ends_on)
        return max((last - first).days + 1, 0)

    def is_handover(self, other: Window) -> bool:
        return (
            self.shared_days(other) == 1
            and self.starts_on != other.starts_on
            and self.ends_on != other.ends_on
        )

    def overlaps(self, other: Window) -> bool:
        return self.shared_days(other) > 0 and not self.is_handover(other)


@dataclass(frozen=True)
class Held:

    window: Window
    reference: str = ""
    booking_id: uuid.UUID | None = None
    subject: str = ""


@dataclass(frozen=True)
class Clash:

    code: str
    message: str
    reference: str = ""
    blocking: bool = True


def clashes(
    wanted: Window,
    existing: Iterable[Held],
    *,
    subject: str = "This",
    ignore: uuid.UUID | None = None,
) -> list[Clash]:
    found: list[Clash] = []
    for held in existing:
        if ignore is not None and held.booking_id == ignore:
            continue
        if wanted.overlaps(held.window):
            found.append(
                Clash(
                    "assignment_clash",
                    f"{subject} is already out "
                    f"{held.window.starts_on:%d %b} to "
                    f"{held.window.ends_on:%d %b}"
                    + (f" on {held.reference}" if held.reference else "")
                    + ". Two trips over the same days is one trip that does "
                    "not happen.",
                    reference=held.reference,
                )
            )
        elif wanted.is_handover(held.window):
            found.append(
                Clash(
                    TIGHT_TURNAROUND,
                    f"{subject} finishes and starts again on the same day "
                    + (f"({held.reference})" if held.reference else "")
                    + ". Normal at the coast, worth a look if the two are far "
                    "apart.",
                    reference=held.reference,
                    blocking=False,
                )
            )
    return found


@dataclass(frozen=True)
class Crew:

    name: str
    roles: tuple[str, ...] = ()
    is_active: bool = True
    licence_expires_on: date | None = None

    def can(self, role: str) -> bool:
        if role == DRIVER:
            return any(one in DRIVES for one in self.roles)
        if role == GUIDE:
            return any(one in GUIDES for one in self.roles)
        return role in self.roles


def check_crew(member: Crew, role: str, window: Window) -> list[Clash]:
    if not member.is_active:
        raise AssignmentRefused(
            f"{member.name} is not on the active roster, so they cannot be put "
            f"on a trip. Reactivate them first if that is wrong."
        )
    if role not in CREW_ROLES:
        raise AssignmentRefused(
            f"'{role}' is not something somebody does on a trip. Say "
            f"{', '.join(CREW_ROLES)}."
        )
    if not member.can(role):
        raise AssignmentRefused(
            f"{member.name} is not down as a {role.replace('_', ' ')}. A guide "
            f"who does not drive cannot be sent out with the vehicle."
        )
    out: list[Clash] = []
    if member.licence_expires_on is not None and role in DRIVES:
        if member.licence_expires_on < window.starts_on:
            raise AssignmentRefused(
                f"{member.name}'s licence expired on "
                f"{member.licence_expires_on:%d %B %Y}, before this trip even "
                f"starts."
            )
        if member.licence_expires_on <= window.ends_on:
            raise AssignmentRefused(
                f"{member.name}'s licence expires on "
                f"{member.licence_expires_on:%d %B %Y}, in the middle of this "
                f"trip. Renew it or send somebody else — the group would be "
                f"out there on the day it lapses."
            )
    return out


@dataclass(frozen=True)
class Fleet:

    name: str
    vehicle_type: str = ""
    passenger_capacity: int = 0
    is_active: bool = True


def check_vehicle(vehicle: Fleet) -> None:
    if not vehicle.is_active:
        raise AssignmentRefused(
            f"{vehicle.name} is not in the active fleet, so it cannot be put "
            f"on a trip."
        )


def seats(vehicles: Iterable[Fleet]) -> int:
    return sum(max(one.passenger_capacity, 0) for one in vehicles)


@dataclass(frozen=True)
class Gap:

    code: str
    message: str
    days: int = 0


@dataclass
class Roster:

    reference: str = ""
    departs_on: date | None = None
    pax_count: int = 0
    vehicles: list[Fleet] = field(default_factory=list)
    drivers: list[Crew] = field(default_factory=list)
    guides: list[Crew] = field(default_factory=list)

    @property
    def seats(self) -> int:
        return seats(self.vehicles)


def check_ready(
    roster: Roster, *, today: date, licence_warning_days: int = 30
) -> list[Gap]:
    out: list[Gap] = []
    until = (roster.departs_on - today).days if roster.departs_on else 0

    if not roster.vehicles:
        out.append(
            Gap(
                NO_VEHICLE,
                f"{roster.reference} has no vehicle and leaves in "
                f"{until} day(s).",
                days=until,
            )
        )
    if not roster.drivers:
        out.append(
            Gap(
                NO_DRIVER,
                f"{roster.reference} has no driver and leaves in "
                f"{until} day(s).",
                days=until,
            )
        )
    if roster.vehicles and roster.pax_count > roster.seats:
        short = roster.pax_count - roster.seats
        out.append(
            Gap(
                NOT_ENOUGH_SEATS,
                f"{roster.reference} carries {roster.pax_count} and the "
                f"assigned vehicles seat {roster.seats} — {short} short. Add "
                f"another vehicle.",
                days=until,
            )
        )
    for member in roster.drivers:
        if member.licence_expires_on is None or roster.departs_on is None:
            continue
        notice = (member.licence_expires_on - roster.departs_on).days
        if 0 <= notice <= licence_warning_days:
            out.append(
                Gap(
                    LICENCE_EXPIRING,
                    f"{member.name}'s licence expires {notice} day(s) after "
                    f"{roster.reference} departs. It will not stop this trip; "
                    f"it will stop the next one.",
                    days=until,
                )
            )
    return out


def sort_gaps(gaps: Sequence[Gap]) -> list[Gap]:
    rank = {NO_VEHICLE: 0, NO_DRIVER: 1, NOT_ENOUGH_SEATS: 2, LICENCE_EXPIRING: 3}
    return sorted(gaps, key=lambda one: (one.days, rank.get(one.code, 9)))


def window_for(
    arrival: date, departure: date, *, before_days: int = 0, after_days: int = 0
) -> Window:
    return Window(
        starts_on=arrival - timedelta(days=max(before_days, 0)),
        ends_on=departure + timedelta(days=max(after_days, 0)),
    )


__all__ = [
    "CREW_ROLES",
    "DRIVER",
    "DRIVER_GUIDE",
    "DRIVES",
    "GUIDE",
    "GUIDES",
    "LICENCE_EXPIRING",
    "NOT_ENOUGH_SEATS",
    "NO_DRIVER",
    "NO_VEHICLE",
    "TIGHT_TURNAROUND",
    "AssignmentRefused",
    "Clash",
    "Crew",
    "Fleet",
    "Gap",
    "Held",
    "Roster",
    "Window",
    "check_crew",
    "check_ready",
    "check_vehicle",
    "clashes",
    "seats",
    "sort_gaps",
    "window_for",
]
