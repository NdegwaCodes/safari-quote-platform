from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

INACTIVE = "publish_inactive"
NO_COPY = "publish_no_copy"

NO_IMAGE = "page_no_image"
NO_LOCATION = "page_no_location"
NO_ROOMS = "page_no_room_types"


class PublishRefused(Exception):

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Candidate:

    name: str
    is_active: bool = True
    copy: str | None = None
    images: int = 0
    has_location: bool = False
    room_types: int = 0


def check_publish(candidate: Candidate) -> None:
    if not candidate.is_active:
        raise PublishRefused(
            INACTIVE,
            f"{candidate.name} is not active, so it cannot be sold — and "
            f"advertising something the quote engine will refuse to price is "
            f"worse than not advertising it. Reactivate it first.",
        )
    if not (candidate.copy or "").strip():
        raise PublishRefused(
            NO_COPY,
            f"{candidate.name} has no description, so its page would be a name "
            f"and a photograph. Write the copy first — it is the same "
            f"paragraph the proposals use.",
        )


@dataclass(frozen=True)
class Concern:

    code: str
    message: str


def check_page(candidate: Candidate, *, wants_rooms: bool = False) -> list[Concern]:
    found: list[Concern] = []
    if candidate.images == 0:
        found.append(
            Concern(
                NO_IMAGE,
                f"{candidate.name} has no images, so its page will be text on "
                f"a white background. Nobody books that.",
            )
        )
    if not candidate.has_location:
        found.append(
            Concern(
                NO_LOCATION,
                f"{candidate.name} has no coordinates, so it cannot go on a map.",
            )
        )
    if wants_rooms and candidate.room_types == 0:
        found.append(
            Concern(
                NO_ROOMS,
                f"{candidate.name} has no room types, so the page cannot say "
                f"what you would be staying in.",
            )
        )
    return found


_PLACE_FIELDS = (
    "name",
    "slug",
    "type",
    "country",
    "region",
    "latitude",
    "longitude",
    "description",
)

_PROPERTY_FIELDS = (
    "name",
    "slug",
    "category",
    "star_rating",
    "latitude",
    "longitude",
    "check_in_time",
    "check_out_time",
)

_ACTIVITY_FIELDS = (
    "name",
    "slug",
    "description",
    "duration_minutes",
)


@dataclass(frozen=True)
class Image:

    id: str
    url: str
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None
    is_lead: bool = False


@dataclass(frozen=True)
class Place:

    name: str = ""
    slug: str = ""
    type: str = ""
    country: str = ""
    region: str | None = None
    latitude: Any = None
    longitude: Any = None
    description: str | None = None
    images: list[Image] = field(default_factory=list)
    stays: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Property:

    name: str = ""
    slug: str = ""
    category: str = ""
    star_rating: int | None = None
    latitude: Any = None
    longitude: Any = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    description: str | None = None
    destination: str = ""
    destination_slug: str = ""
    rooms: list[str] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)


@dataclass(frozen=True)
class Experience:

    name: str = ""
    slug: str = ""
    description: str | None = None
    duration_minutes: int | None = None
    destination: str = ""
    destination_slug: str = ""


def _copy(row: Any, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: getattr(row, name, None) for name in names}


def place_of(
    row: Any,
    *,
    images: list[Image] | None = None,
    stays: list[str] | None = None,
    activities: list[str] | None = None,
) -> Place:
    data = _copy(row, _PLACE_FIELDS)
    return Place(
        name=data["name"] or "",
        slug=data["slug"] or "",
        type=data["type"] or "",
        country=data["country"] or "",
        region=data["region"],
        latitude=data["latitude"],
        longitude=data["longitude"],
        description=data["description"],
        images=images or [],
        stays=stays or [],
        activities=activities or [],
    )


def property_of(
    row: Any,
    *,
    copy: str | None = None,
    destination: str = "",
    destination_slug: str = "",
    rooms: list[str] | None = None,
    images: list[Image] | None = None,
) -> Property:
    data = _copy(row, _PROPERTY_FIELDS)
    return Property(
        name=data["name"] or "",
        slug=data["slug"] or "",
        category=data["category"] or "",
        star_rating=data["star_rating"],
        latitude=data["latitude"],
        longitude=data["longitude"],
        check_in_time=data["check_in_time"],
        check_out_time=data["check_out_time"],
        description=copy if copy is not None else getattr(row, "blurb", None),
        destination=destination,
        destination_slug=destination_slug,
        rooms=rooms or [],
        images=images or [],
    )


def experience_of(
    row: Any, *, destination: str = "", destination_slug: str = ""
) -> Experience:
    data = _copy(row, _ACTIVITY_FIELDS)
    return Experience(
        name=data["name"] or "",
        slug=data["slug"] or "",
        description=data["description"],
        duration_minutes=data["duration_minutes"],
        destination=destination,
        destination_slug=destination_slug,
    )


__all__ = [
    "INACTIVE",
    "NO_COPY",
    "NO_IMAGE",
    "NO_LOCATION",
    "NO_ROOMS",
    "Candidate",
    "Concern",
    "Experience",
    "Image",
    "Place",
    "Property",
    "PublishRefused",
    "check_page",
    "check_publish",
    "experience_of",
    "place_of",
    "property_of",
]
