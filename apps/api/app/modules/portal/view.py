from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

EXPIRED = "portal_link_expired"
REVOKED = "portal_link_revoked"
CANCELLED = "portal_booking_cancelled"


class AccessRefused(Exception):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Grant:

    expires_on: date
    revoked: bool = False
    revoke_reason: str | None = None
    booking_status: str = "provisional"
    booking_reference: str = ""


def check_access(grant: Grant, *, today: date) -> None:
    if grant.booking_status == "cancelled":
        raise AccessRefused(
            CANCELLED,
            f"Booking {grant.booking_reference} has been cancelled, so there "
            f"is no trip to show. If that is not right, your consultant can "
            f"tell you what happened — the record of it is not gone.",
        )
    if grant.revoked:
        raise AccessRefused(
            REVOKED,
            "This link has been withdrawn. Ask your consultant for a new one; "
            "your booking is unaffected.",
        )
    if grant.expires_on < today:
        raise AccessRefused(
            EXPIRED,
            f"This link stopped working on {grant.expires_on:%d %B %Y}. Your "
            f"consultant can send a fresh one — nothing about your booking has "
            f"changed.",
        )


def default_expiry(
    departure: date, *, after_days: int, today: date, minimum_days: int = 30
) -> date:
    return max(
        departure + _days(after_days),
        today + _days(minimum_days),
    )


def _days(count: int):
    from datetime import timedelta

    return timedelta(days=count)


@dataclass(frozen=True)
class Movement:
    label: str
    minutes: int | None = None


@dataclass(frozen=True)
class Day:

    number: int
    on: date | None
    destination: str = ""
    property_name: str = ""
    board: str = ""
    movements: list[Movement] = field(default_factory=list)
    excursions: list[str] = field(default_factory=list)
    is_arrival: bool = False
    is_departure: bool = False
    has_night: bool = True


@dataclass(frozen=True)
class Stay:

    sequence: int
    destination: str = ""
    property_name: str = ""
    room_type: str = ""
    board: str = ""
    rooms: int = 0
    nights: int = 0


@dataclass(frozen=True)
class Trip:

    reference: str = ""
    status: str = ""
    arrival_date: date | None = None
    departure_date: date | None = None
    pax_count: int = 0
    total: Decimal = Decimal(0)
    currency: str = ""
    property_name: str = ""
    room_type: str = ""
    board: str = ""
    nights: int = 0
    description: str | None = None
    stays: list[Stay] = field(default_factory=list)
    days: list[Day] = field(default_factory=list)
    included: list[str] = field(default_factory=list)


_OPTION_FIELDS = (
    "accommodation_name",
    "room_type_name",
    "meal_plan_name",
    "nights",
    "blurb",
    "activities",
    "legs",
    "days",
)


def option_of(snapshot: dict[str, Any], option_id: str | None) -> dict[str, Any]:
    options = [one for one in snapshot.get("options", []) if isinstance(one, dict)]
    if not options:
        return {}
    if option_id:
        found = next(
            (one for one in options if str(one.get("option_id")) == str(option_id)),
            None,
        )
        if found is not None:
            return found
    recommended = next(
        (one for one in options if one.get("is_recommended")), None
    )
    return recommended or options[0]


def trip_of(
    snapshot: dict[str, Any],
    *,
    option_id: str | None,
    reference: str,
    status: str,
    arrival: date | None,
    departure: date | None,
    pax_count: int,
    total: Decimal,
    currency: str,
) -> Trip:
    option = option_of(snapshot, option_id)
    picked = {key: option.get(key) for key in _OPTION_FIELDS}
    return Trip(
        reference=reference,
        status=status,
        arrival_date=arrival,
        departure_date=departure,
        pax_count=pax_count,
        total=total,
        currency=(currency or "").upper(),
        property_name=str(picked.get("accommodation_name") or ""),
        room_type=str(picked.get("room_type_name") or ""),
        board=str(picked.get("meal_plan_name") or ""),
        nights=int(picked.get("nights") or 0),
        description=(
            str(picked["blurb"]) if picked.get("blurb") else None
        ),
        stays=_stays(picked.get("legs")),
        days=_days_of(picked.get("days")),
        included=[str(one) for one in (picked.get("activities") or [])],
    )


def _stays(legs: Any) -> list[Stay]:
    if not isinstance(legs, list):
        return []
    out: list[Stay] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        out.append(
            Stay(
                sequence=int(leg.get("sequence") or 0),
                destination=str(leg.get("destination_name") or ""),
                property_name=str(leg.get("accommodation_name") or ""),
                room_type=str(leg.get("room_type_name") or ""),
                board=str(leg.get("meal_plan_name") or ""),
                rooms=int(leg.get("rooms_required") or 0),
                nights=int(leg.get("nights") or 0),
            )
        )
    return sorted(out, key=lambda one: one.sequence)


def _days_of(days: Any) -> list[Day]:
    if not isinstance(days, list):
        return []
    out: list[Day] = []
    for day in days:
        if not isinstance(day, dict):
            continue
        out.append(
            Day(
                number=int(day.get("number") or 0),
                on=_date(day.get("date")),
                destination=str(day.get("destination") or ""),
                property_name=str(day.get("property_name") or ""),
                board=str(day.get("board") or ""),
                movements=_movements(day.get("movements")),
                excursions=[str(one) for one in (day.get("excursions") or [])],
                is_arrival=bool(day.get("is_arrival")),
                is_departure=bool(day.get("is_departure")),
                has_night=bool(day.get("has_night", True)),
            )
        )
    return sorted(out, key=lambda one: one.number)


def _movements(movements: Any) -> list[Movement]:
    if not isinstance(movements, list):
        return []
    out: list[Movement] = []
    for one in movements:
        if isinstance(one, str):
            out.append(Movement(label=one))
        elif isinstance(one, dict):
            minutes = one.get("minutes")
            out.append(
                Movement(
                    label=str(one.get("label") or ""),
                    minutes=int(minutes) if minutes is not None else None,
                )
            )
    return out


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


__all__ = [
    "CANCELLED",
    "EXPIRED",
    "REVOKED",
    "AccessRefused",
    "Day",
    "Grant",
    "Movement",
    "Stay",
    "Trip",
    "check_access",
    "default_expiry",
    "option_of",
    "trip_of",
]
