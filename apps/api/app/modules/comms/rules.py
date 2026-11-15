from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

INBOUND = "inbound"
OUTBOUND = "outbound"
INTERNAL = "internal"
DIRECTIONS = (INBOUND, OUTBOUND, INTERNAL)

CALL = "call"
EMAIL = "email"
WHATSAPP = "whatsapp"
SMS = "sms"
MEETING = "meeting"
NOTE = "note"
COMMON_CHANNELS = (CALL, EMAIL, WHATSAPP, SMS, MEETING, NOTE, "other")

TIMED_CHANNELS = (CALL, MEETING)


class LogRefused(ValueError):
    pass


def normalise_channel(value: str | None) -> str:
    cleaned = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return cleaned or NOTE


def normalise_direction(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned not in DIRECTIONS:
        raise LogRefused(
            f"'{value}' is not a direction. Say {', '.join(DIRECTIONS)} — "
            f"'internal' for a note to ourselves, which is not contact with "
            f"the client."
        )
    return cleaned


@dataclass(frozen=True)
class Logged:

    channel: str
    direction: str
    occurred_at: datetime
    body: str = ""
    reached: bool | None = None
    duration_minutes: int | None = None


def check_logged(entry: Logged, *, now: datetime) -> None:
    if entry.occurred_at > now:
        raise LogRefused(
            "This is dated in the future, so it has not happened yet. Log the "
            "call after making it; the next step goes on the lead as its next "
            "action."
        )
    if not (entry.body or "").strip():
        raise LogRefused(
            "Say what was said. An entry with no words records that contact "
            "happened and nothing about it, so the next person reads 'called "
            "Tuesday' and has to call again anyway."
        )
    if entry.direction == INTERNAL and entry.reached is not None:
        raise LogRefused(
            "An internal note is not a conversation with the client, so there "
            "is nobody it could have reached."
        )
    if entry.duration_minutes is not None:
        if entry.duration_minutes <= 0:
            raise LogRefused(
                "A call has to have lasted some time. Leave the length off if "
                "it is not known, and record an unanswered one as not reached."
            )
        if entry.channel not in TIMED_CHANNELS:
            raise LogRefused(
                "A length only makes sense on a call or a meeting; an email "
                "does not last nineteen minutes."
            )
        if entry.reached is False:
            raise LogRefused(
                "A call that was not answered has no length. Record the "
                "attempt with no duration — that it was attempted is the fact "
                "worth keeping."
            )


@dataclass(frozen=True)
class Contact:

    channel: str
    direction: str
    occurred_at: datetime
    reached: bool | None = None
    voided: bool = False

    @property
    def counts(self) -> bool:
        return not self.voided and self.direction in (INBOUND, OUTBOUND)


@dataclass
class Contacted:

    entries: int = 0
    contacts: int = 0
    last_contact_at: datetime | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    chases: int = 0
    by_channel: dict[str, int] = field(default_factory=dict)
    by_direction: dict[str, int] = field(default_factory=dict)
    unreached_calls: int = 0

    @property
    def ever_contacted(self) -> bool:
        return self.last_contact_at is not None

    @property
    def has_replied(self) -> bool:
        return self.last_inbound_at is not None


def history(entries: Iterable[Contact]) -> Contacted:
    rows = sorted(entries, key=lambda one: one.occurred_at)
    out = Contacted(entries=len(rows))
    for row in rows:
        out.by_channel[row.channel] = out.by_channel.get(row.channel, 0) + 1
        out.by_direction[row.direction] = out.by_direction.get(row.direction, 0) + 1
        if not row.counts:
            continue
        out.contacts += 1
        out.last_contact_at = row.occurred_at
        if row.direction == INBOUND:
            out.last_inbound_at = row.occurred_at
            out.chases = 0
        else:
            out.last_outbound_at = row.occurred_at
            out.chases += 1
            if row.channel == CALL and row.reached is False:
                out.unreached_calls += 1
    return out


def first_response_hours(
    arrived_at: datetime, entries: Iterable[Contact]
) -> Decimal | None:
    outbound = [
        one.occurred_at for one in entries if one.counts and one.direction == OUTBOUND
    ]
    if not outbound:
        return None
    gap = (min(outbound) - arrived_at).total_seconds() / 3600
    return Decimal(max(gap, 0.0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Silence:

    chases: int
    days: int
    since: datetime
    ever_replied: bool

    @property
    def message(self) -> str:
        who = (
            "since they last replied"
            if self.ever_replied
            else "and they have never replied"
        )
        return (
            f"{self.chases} attempt(s) {who}, the last {self.days} day(s) ago. "
            f"Whether that is a no is a judgement about this client, not "
            f"something a report can make."
        )


def silence(
    log: Contacted, *, now: datetime, after_chases: int = 2, after_days: int = 7
) -> Silence | None:
    if log.chases < after_chases or log.last_outbound_at is None:
        return None
    days = (now - log.last_outbound_at).days
    if days < after_days:
        return None
    return Silence(
        chases=log.chases,
        days=days,
        since=log.last_outbound_at,
        ever_replied=log.has_replied,
    )


def median_hours(values: Sequence[Decimal]) -> Decimal | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    pair = (ordered[middle - 1] + ordered[middle]) / 2
    return pair.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


__all__ = [
    "CALL",
    "COMMON_CHANNELS",
    "DIRECTIONS",
    "EMAIL",
    "INBOUND",
    "INTERNAL",
    "MEETING",
    "NOTE",
    "OUTBOUND",
    "TIMED_CHANNELS",
    "WHATSAPP",
    "Contact",
    "Contacted",
    "LogRefused",
    "Logged",
    "Silence",
    "check_logged",
    "first_response_hours",
    "history",
    "median_hours",
    "normalise_channel",
    "normalise_direction",
    "silence",
]
