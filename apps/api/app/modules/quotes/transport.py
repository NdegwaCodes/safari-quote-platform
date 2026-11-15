from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.modules.quotes.packages import Problem

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps this module ORM-free
    from app.modules.quotes.models import QuoteTransportSegment

LINE_HAUL = "line_haul"
TRANSFER = "transfer"
KINDS = (LINE_HAUL, TRANSFER)

PRICED_MODES = ("road", "rail")
NAMED_ONLY_MODES = ("air",)

TRANSFERS_PER_RAIL_LEG = 2

_LINE_BASIS = {
    "per_person": "per_person",
    "per_vehicle": "per_group",
    "per_leg": "per_group",
}

NO_SEGMENTS = "transport_none"
UNKNOWN_KIND = "transport_unknown_kind"
UNKNOWN_MODE = "transport_unknown_mode"
FLIGHT_NAMED = "transport_flight_named_not_priced"
RAIL_WITHOUT_TRANSFERS = "transport_rail_without_transfers"
NO_DESTINATION = "transport_no_destination"
MISSING_MOVEMENTS = "transport_movements_short"
VVIP_NOT_OPTIONAL = "transport_vvip_not_optional"


@dataclass(frozen=True)
class Segment:

    sequence: int
    kind: str
    mode: str
    travel_class: str = ""
    destination: str | None = None
    vehicle_type: str | None = None
    has_vehicle: bool = False
    units: int = 1
    is_optional: bool = False
    is_vvip: bool = False
    label: str = ""


def segments_of(rows: Iterable[QuoteTransportSegment]) -> list[Segment]:
    return _order(
        [
            Segment(
                sequence=row.sequence,
                kind=row.kind,
                mode=row.mode,
                travel_class=row.travel_class or "",
                destination=str(row.destination_id) if row.destination_id else None,
                vehicle_type=row.vehicle_type,
                has_vehicle=row.vehicle_id is not None,
                units=row.units,
                is_optional=row.is_optional,
                is_vvip=row.is_vvip,
                label=row.description or "",
            )
            for row in rows
        ]
    )


def line_basis(cost_basis: str) -> str:
    try:
        return _LINE_BASIS[cost_basis]
    except KeyError:
        raise ValueError(f"unknown transport cost basis: {cost_basis!r}") from None


def movements_needed(legs: int) -> int:
    return max(0, legs) + 1


def priceable(segments: list[Segment]) -> list[Segment]:
    return [s for s in _order(segments) if s.mode in PRICED_MODES and not s.is_optional]


def optional_extras(segments: list[Segment]) -> list[Segment]:
    return [s for s in _order(segments) if s.mode in PRICED_MODES and s.is_optional]


def named_only(segments: list[Segment]) -> list[Segment]:
    return [s for s in _order(segments) if s.mode in NAMED_ONLY_MODES]


def check(segments: list[Segment], *, legs: int = 1) -> list[Problem]:
    if not segments:
        return [
            Problem(
                NO_SEGMENTS,
                "This quote carries no transport at all. If the client is "
                "driving themselves, say so on the document; otherwise the road "
                "cost is missing from every option.",
                blocking=False,
            )
        ]

    problems: list[Problem] = []
    ordered = _order(segments)

    for segment in ordered:
        if segment.kind not in KINDS:
            problems.append(
                Problem(
                    UNKNOWN_KIND,
                    f"Segment {segment.sequence} is a {segment.kind!r}, which is "
                    f"neither a line haul nor a transfer, so nothing knows how "
                    f"to price it.",
                    sequence=segment.sequence,
                )
            )
        if segment.mode not in PRICED_MODES and segment.mode not in NAMED_ONLY_MODES:
            modes = ", ".join(PRICED_MODES)
            problems.append(
                Problem(
                    UNKNOWN_MODE,
                    f"Segment {segment.sequence} travels by {segment.mode!r}, "
                    f"which is not a mode we sell ({modes}).",
                    sequence=segment.sequence,
                )
            )

    for segment in named_only(ordered):
        problems.append(
            Problem(
                FLIGHT_NAMED,
                f"Segment {segment.sequence} is a flight, so it is named on the "
                f"itinerary and carries no price: Acacia does not ticket air "
                f"travel. List the fare as an exclusion so the client knows to "
                f"book it themselves.",
                sequence=segment.sequence,
                blocking=False,
            )
        )

    for segment in ordered:
        if (
            segment.mode in PRICED_MODES
            and not segment.has_vehicle
            and not segment.destination
        ):
            problems.append(
                Problem(
                    NO_DESTINATION,
                    f"Segment {segment.sequence} names no destination, and every "
                    f"fare is keyed on one — the same vehicle costs differently "
                    f"in different places — so there is no tariff to price it "
                    f"from.",
                    sequence=segment.sequence,
                )
            )

    rail = [s for s in ordered if s.kind == LINE_HAUL and s.mode == "rail"]
    transfers = [s for s in ordered if s.kind == TRANSFER and s.mode in PRICED_MODES]
    required = len(rail) * TRANSFERS_PER_RAIL_LEG
    if rail and len(transfers) < required:
        problems.append(
            Problem(
                RAIL_WITHOUT_TRANSFERS,
                f"{len(rail)} rail line haul(s) need {required} transfer legs "
                f"(pickup to terminus, terminus to hotel, and the same in "
                f"reverse) and this quote has {len(transfers)}. A train leaves "
                f"from a terminus nobody sleeps at, so the missing legs are a "
                f"cost the client would not be charged for.",
            )
        )

    movements = [s for s in ordered if s.mode in PRICED_MODES and not s.is_optional]
    needed = movements_needed(legs)
    if not any(s.has_vehicle for s in ordered) and len(movements) < needed:
        problems.append(
            Problem(
                MISSING_MOVEMENTS,
                f"An itinerary of {legs} stay(s) takes {needed} movements — one "
                f"per transition plus arrival and departure — and this quote "
                f"prices {len(movements)}. Either the missing legs are unpriced "
                f"or the client is arranging them, and the document should say "
                f"which.",
                blocking=False,
            )
        )

    for segment in ordered:
        if segment.is_vvip and not segment.is_optional:
            problems.append(
                Problem(
                    VVIP_NOT_OPTIONAL,
                    f"Segment {segment.sequence} is VVIP transport inside the "
                    f"package price. It is quoted as an add-on, so that the "
                    f"options stay a comparison of the same journey.",
                    sequence=segment.sequence,
                    blocking=False,
                )
            )

    return problems


def _order(segments: list[Segment]) -> list[Segment]:
    return sorted(segments, key=lambda segment: segment.sequence)
