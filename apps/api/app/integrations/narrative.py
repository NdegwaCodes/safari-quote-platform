from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

ACCOMMODATION = "accommodation"
DESTINATION = "destination"
SUBJECTS = (ACCOMMODATION, DESTINATION)


class NarrativeUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Brief:

    subject: str
    name: str
    category: str = ""
    place: str = ""
    meal_plans: tuple[str, ...] = ()
    room_types: tuple[str, ...] = ()
    steer: str = ""
    words: int = 80

    def __post_init__(self) -> None:
        if self.subject not in SUBJECTS:
            raise ValueError(f"unknown narrative subject: {self.subject!r}")
        if not self.name:
            raise ValueError("a narrative needs something to be about")
        if self.words <= 0:
            raise ValueError("words must be positive")

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "name": self.name,
            "category": self.category,
            "place": self.place,
            "meal_plans": list(self.meal_plans),
            "room_types": list(self.room_types),
            "steer": self.steer,
            "words": self.words,
        }


@dataclass(frozen=True)
class Draft:

    text: str
    provider: str
    model: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("a draft with no text is not a draft")
        if not self.provider:
            raise ValueError("a draft must say what produced it")


HAND = "hand"


class NarrativeProvider(Protocol):

    async def write(self, brief: Brief) -> Draft: ...


class UnavailableProvider:

    name = "unavailable"

    async def write(self, brief: Brief) -> Draft:
        raise NarrativeUnavailable(
            "No narrative provider is configured, so copy cannot be generated. "
            "Write the description and it goes through the same review before "
            "it reaches a client."
        )
