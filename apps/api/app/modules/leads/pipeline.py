from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.modules.comms.rules import median_hours

NO_NEXT_ACTION = "lead_no_next_action"
OVERDUE = "lead_next_action_overdue"
DUE = "lead_next_action_due"
UNOWNED = "lead_unowned"
STALE = "lead_untouched"
NEVER_CONTACTED = "lead_never_contacted"
UNANSWERED = "lead_chased_unanswered"


class StageRefused(ValueError):
    pass


@dataclass(frozen=True)
class Stage:

    key: str
    name: str
    sort_order: int = 0
    is_default: bool = False
    is_won: bool = False
    is_lost: bool = False

    @property
    def is_terminal(self) -> bool:
        return self.is_won or self.is_lost


def check_pipeline(stages: Sequence[Stage]) -> list[str]:
    problems: list[str] = []
    if not stages:
        return ["The pipeline has no stages, so a lead has nowhere to arrive."]
    defaults = [stage for stage in stages if stage.is_default]
    if not defaults:
        problems.append(
            "No stage is marked as the one new enquiries arrive at, so a lead "
            "would have nowhere to start."
        )
    elif len(defaults) > 1:
        problems.append(
            "More than one stage is marked as where new enquiries arrive: "
            + ", ".join(stage.name for stage in defaults)
            + ". A lead can only start in one."
        )
    if not [stage for stage in stages if stage.is_won]:
        problems.append(
            "No stage means won, so nothing can ever be counted as converted."
        )
    if not [stage for stage in stages if stage.is_lost]:
        problems.append(
            "No stage means lost, so a dead lead would sit in the pipeline "
            "forever and every stage count would be wrong."
        )
    both = [stage for stage in stages if stage.is_won and stage.is_lost]
    if both:
        problems.append(
            "A stage cannot mean both won and lost: "
            + ", ".join(stage.name for stage in both)
        )
    keys = [stage.key for stage in stages]
    if len(keys) != len(set(keys)):
        problems.append("Two stages share a key, so one of them is unreachable.")
    return problems


def check_move(
    current: Stage, target: Stage, *, lost_reason: str | None = None
) -> None:
    if current.key == target.key:
        raise StageRefused(
            f"This lead is already at {target.name}. Moving it there again "
            f"would record a stage change that did not happen."
        )
    if target.is_lost and not (lost_reason or "").strip():
        raise StageRefused(
            f"Say why the lead was lost before moving it to {target.name}. "
            f"'We lost eleven' is a fact nobody can act on; 'seven of them on "
            f"price' is a decision."
        )


@dataclass(frozen=True)
class Attention:

    code: str
    message: str
    days: int = 0


@dataclass(frozen=True)
class Watched:

    name: str
    stage: Stage
    stage_since: date | None = None
    next_action_on: date | None = None
    owner: str | None = None
    last_contact_on: date | None = None
    last_inbound_on: date | None = None
    last_answered_on: date | None = None
    chases: int = 0
    logged: int = 0


def attention(
    lead: Watched,
    *,
    today: date,
    stale_after_days: int = 14,
    chase_threshold: int = 3,
) -> list[Attention]:
    if lead.stage.is_terminal:
        return []

    out: list[Attention] = []
    if lead.last_answered_on is None:
        waiting = (today - lead.stage_since).days if lead.stage_since else 0
        if lead.last_inbound_on is not None:
            what = (
                f"{lead.name} has written and nobody has replied"
                + (f", {waiting} day(s) later" if waiting else "")
                + "."
            )
        else:
            what = (
                f"Nobody has contacted {lead.name} at all"
                + (f", {waiting} day(s) after the enquiry arrived" if waiting else "")
                + ("." if not lead.logged else ", though there are notes on it.")
            )
        out.append(Attention(NEVER_CONTACTED, what, days=waiting))
    if lead.next_action_on is None:
        out.append(
            Attention(
                NO_NEXT_ACTION,
                f"{lead.name} has no next action, so nothing will bring it back "
                f"to anybody's attention.",
            )
        )
    elif lead.next_action_on < today:
        late = (today - lead.next_action_on).days
        out.append(
            Attention(
                OVERDUE,
                f"{lead.name}: the next action was due {late} day(s) ago.",
                days=late,
            )
        )
    elif lead.next_action_on == today:
        out.append(Attention(DUE, f"{lead.name}: the next action is due today."))

    if lead.owner is None:
        out.append(
            Attention(
                UNOWNED,
                f"{lead.name} has no owner, so it is nobody's to lose.",
            )
        )

    if lead.chases >= chase_threshold:
        out.append(
            Attention(
                UNANSWERED,
                f"{lead.name} has been chased {lead.chases} time(s) "
                + (
                    "since they last replied"
                    if lead.last_inbound_on
                    else "and has never replied"
                )
                + ". Whether that is a no is a judgement about this client, "
                "not something a report can make.",
                days=lead.chases,
            )
        )

    since, what = (
        (lead.last_contact_on, "has not been contacted for")
        if lead.last_contact_on is not None
        else (lead.stage_since, f"has been at {lead.stage.name} for")
    )
    if since is not None:
        idle = (today - since).days
        if idle >= stale_after_days:
            out.append(
                Attention(
                    STALE,
                    f"{lead.name} {what} {idle} "
                    f"day(s). Not necessarily cold — a honeymoon enquiry for "
                    f"next August is not stale at three weeks — but worth a "
                    f"decision.",
                    days=idle,
                )
            )
    return out


@dataclass(frozen=True)
class Counted:

    stage: Stage
    source: str = "other"
    stage_since: date | None = None
    budget_amount: Decimal | None = None
    budget_currency: str | None = None
    quotes: int = 0
    accepted: bool = False
    first_response_hours: Decimal | None = None


@dataclass
class StageCount:
    stage: str
    name: str
    leads: int = 0
    median_days: int | None = None


@dataclass
class SourceCount:
    source: str
    leads: int = 0
    quoted: int = 0
    won: int = 0

    @property
    def win_rate(self) -> Decimal | None:
        if not self.leads:
            return None
        return (Decimal(self.won) / Decimal(self.leads)).quantize(Decimal("0.0001"))


@dataclass
class Pipeline:
    stages: list[StageCount] = field(default_factory=list)
    sources: list[SourceCount] = field(default_factory=list)
    median_first_response_hours: Decimal | None = None
    never_answered: int = 0
    open_budget: dict[str, Decimal] = field(default_factory=dict)
    open_leads: int = 0
    won_leads: int = 0
    lost_leads: int = 0

    @property
    def win_rate(self) -> Decimal | None:
        decided = self.won_leads + self.lost_leads
        if not decided:
            return None
        return (Decimal(self.won_leads) / Decimal(decided)).quantize(
            Decimal("0.0001")
        )


def _median(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


def summarise(
    leads: Iterable[Counted], stages: Sequence[Stage], *, today: date
) -> Pipeline:
    out = Pipeline()
    dwell: dict[str, list[int]] = {}
    by_source: dict[str, SourceCount] = {}
    counts: dict[str, int] = {stage.key: 0 for stage in stages}
    watched = list(leads)

    for lead in watched:
        counts[lead.stage.key] = counts.get(lead.stage.key, 0) + 1
        key = lead.stage.key
        if lead.stage_since is not None:
            dwell.setdefault(key, []).append((today - lead.stage_since).days)

        if lead.stage.is_won:
            out.won_leads += 1
        elif lead.stage.is_lost:
            out.lost_leads += 1
        else:
            out.open_leads += 1
            if lead.budget_amount is not None and lead.budget_currency:
                currency = lead.budget_currency.upper()
                out.open_budget[currency] = (
                    out.open_budget.get(currency, Decimal(0)) + lead.budget_amount
                )

        source = by_source.setdefault(
            lead.source, SourceCount(source=lead.source)
        )
        source.leads += 1
        if lead.quotes:
            source.quoted += 1
        if lead.accepted or lead.stage.is_won:
            source.won += 1

    out.stages = [
        StageCount(
            stage=stage.key,
            name=stage.name,
            leads=counts.get(stage.key, 0),
            median_days=_median(dwell.get(stage.key, [])),
        )
        for stage in sorted(stages, key=lambda one: one.sort_order)
    ]
    out.sources = sorted(by_source.values(), key=lambda one: -one.leads)

    answered = [
        lead.first_response_hours
        for lead in watched
        if lead.first_response_hours is not None
    ]
    out.median_first_response_hours = median_hours(answered)
    out.never_answered = len(watched) - len(answered)
    return out


def since_days(when: datetime | date | None, *, today: date) -> int | None:
    if when is None:
        return None
    day = when.date() if isinstance(when, datetime) else when
    return (today - day).days


def next_action_default(*, today: date, days: int = 3) -> date:
    return today + timedelta(days=max(0, days))
