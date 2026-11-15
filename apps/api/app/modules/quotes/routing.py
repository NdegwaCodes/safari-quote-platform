from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.modules.quotes.packages import Problem

NO_ROUTE = "route_not_on_file"
NO_ENDPOINTS = "route_endpoints_missing"
WRONG_VEHICLE = "route_vehicle_not_suitable"
NO_FUEL_PRICE = "route_fuel_price_missing"

DAYS_PER_MOVEMENT = 1


def plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


@dataclass(frozen=True)
class Road:

    label: str
    distance_km: Decimal
    drive_time_minutes: int
    required_vehicle_types: tuple[str, ...] = ()
    reversed_lookup: bool = False
    notes: str = ""
    source: str = ""

    @property
    def hours(self) -> Decimal:
        return (Decimal(self.drive_time_minutes) / Decimal(60)).quantize(
            Decimal("0.01")
        )


def normalise_types(values: Iterable[str] | None) -> tuple[str, ...]:
    seen: list[str] = []
    for value in values or ():
        cleaned = (value or "").strip().lower()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return tuple(seen)


def vehicle_is_suitable(required: Iterable[str] | None, offered: str | None) -> bool:
    wanted = normalise_types(required)
    if not wanted:
        return True
    return (offered or "").strip().lower() in wanted


def check_vehicle(
    *,
    label: str,
    road: Road,
    offered: str | None,
    sequence: int | None = None,
) -> Problem | None:
    if vehicle_is_suitable(road.required_vehicle_types, offered):
        return None
    takes = ", ".join(road.required_vehicle_types)
    named = (offered or "").strip() or "no vehicle"
    return Problem(
        WRONG_VEHICLE,
        f"{label} is quoted on {named}, but {road.label or 'this route'} takes "
        f"{takes}. The quote is under-priced by the difference and the drive "
        f"cannot be run as sold."
        + (f" Route note: {road.notes}" if road.notes else ""),
        sequence=sequence,
    )


def check_endpoints(
    *, label: str, has_origin: bool, has_destination: bool, sequence: int | None = None
) -> Problem | None:
    if has_origin and has_destination:
        return None
    missing = "start" if not has_origin else "destination"
    return Problem(
        NO_ENDPOINTS,
        f"{label} is driven on our own vehicle but names no {missing}, so its "
        f"route — and with it the distance, the drive time and the fuel — "
        f"cannot be found. Set both ends of the movement.",
        sequence=sequence,
    )


def missing_route(
    *, label: str, sequence: int | None = None, on: object | None = None
) -> Problem:
    when = f" on {on}" if on is not None else ""
    return Problem(
        NO_ROUTE,
        f"{label} has no route on file for those two places{when}, so the "
        f"drive carries no distance and no fuel. Enter the route — the driven "
        f"kilometres, the time it takes, and the vehicles the road takes.",
        sequence=sequence,
    )


def missing_fuel_price(
    *, label: str, fuel_type: str, sequence: int | None = None
) -> Problem:
    return Problem(
        NO_FUEL_PRICE,
        f"{label} is driven on a {fuel_type} vehicle and no {fuel_type} price "
        f"is on file for that date, so the fuel is uncosted. Load the pump "
        f"price.",
        sequence=sequence,
    )
