from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.integrations.narrative import ACCOMMODATION
from app.modules.accommodations.models import Accommodation
from app.modules.destinations.models import Destination
from app.modules.narratives.service import NarrativeService
from app.modules.pricing.config import PricingConfig
from app.modules.pricing.service import PricingConfigService
from app.modules.quotes.itinerary import (
    Movement,
)
from app.modules.quotes.itinerary import (
    build as build_programme,
)
from app.modules.quotes.itinerary import (
    check as check_itinerary,
)
from app.modules.quotes.models import (
    Quote,
    QuoteOption,
    QuoteOptionLeg,
    QuoteRejectedCandidate,
    QuoteVersion,
    QuoteVersionOption,
)
from app.modules.quotes.option_pricing import (
    OptionCosting,
    OptionPricingResult,
    OptionPricingService,
)
from app.modules.quotes.options import needs_chef
from app.modules.quotes.outcomes import (
    ACCEPTED,
    DRAFT,
    Conversion,
    Decided,
    OutcomeRefused,
    check_outcome,
    convert,
)
from app.modules.quotes.packages import Leg
from app.modules.quotes.packages import check as check_package
from app.modules.quotes.routing import Road
from app.modules.quotes.schemas import (
    QuoteOptionIn,
    QuoteOptionUpdate,
    RejectedCandidateIn,
)
from app.modules.quotes.sequencing import Sequenced
from app.modules.quotes.sequencing import sequence as check_sequence
from app.modules.quotes.service import QuoteService
from app.modules.quotes.transport import check as check_transport
from app.modules.quotes.transport import segments_of
from app.modules.residence.models import ResidenceCategory
from app.modules.transport.service import RouteService

BLOCKING = "blocking"
ADVISORY = "advisory"

_NOT_NULLABLE = frozenset({"sort_order", "is_comparable", "agent_cover_fee"})


@dataclass(frozen=True)
class Problem:

    severity: str
    code: str
    message: str


@dataclass
class Readiness:

    is_ready: bool
    catered_options: int
    self_catering_options: int
    problems: list[Problem]


class QuoteAssemblyService:
    def __init__(self, db: AsyncSession):
        self.db = db


    async def add_option(
        self, quote_id: uuid.UUID, payload: QuoteOptionIn
    ) -> QuoteOption:
        quote = await self._load(quote_id)
        self._refuse_if_issued(quote)
        accommodation = await self.db.get(Accommodation, payload.accommodation_id)
        if accommodation is None:
            raise NotFoundError("Accommodation not found.")
        if not payload.legs and any(
            o.accommodation_id == payload.accommodation_id and not o.legs
            for o in quote.options
        ):
            raise AppError(
                f"{accommodation.name} is already an option on this quote. A client "
                f"choosing between two entries for the same property is a mistake, "
                f"not a choice."
            )
        if payload.legs:
            existing = {
                tuple(
                    (leg.sequence, leg.accommodation_id, leg.check_in, leg.check_out)
                    for leg in sorted(o.legs, key=lambda entry: entry.sequence)
                )
                for o in quote.options
                if o.legs
            }
            QuoteService(self.db)._check_package(
                payload,
                index=len(quote.options) + 1,
                arrival=quote.arrival_date,
                departure=quote.departure_date,
                seen=existing,
            )
        highest = max((o.sort_order for o in quote.options), default=0)
        option = QuoteOption(
            quote_id=quote.id,
            accommodation_id=payload.accommodation_id,
            is_recommended=payload.is_recommended,
            sort_order=payload.sort_order or highest + 1,
            agent_cover_fee=payload.agent_cover_fee,
            chef_fee_per_meal=payload.chef_fee_per_meal,
            manual_meal_cost=payload.manual_meal_cost,
            is_comparable=payload.is_comparable,
            notes=payload.notes,
        )
        for entry in payload.legs:
            option.legs.append(
                QuoteOptionLeg(
                    sequence=entry.sequence,
                    destination_id=entry.destination_id,
                    accommodation_id=entry.accommodation_id,
                    requested_meal_plan_id=entry.requested_meal_plan_id,
                    check_in=entry.check_in,
                    check_out=entry.check_out,
                )
            )
        self.db.add(option)
        await self.db.flush()
        if payload.is_recommended:
            await self._make_sole_recommendation(quote.id, option.id)
        await self.db.commit()
        return (
            await self.db.execute(select(QuoteOption).where(QuoteOption.id == option.id))
        ).scalar_one()

    async def update_option(
        self, quote_id: uuid.UUID, option_id: uuid.UUID, payload: QuoteOptionUpdate
    ) -> QuoteOption:
        quote = await self._load(quote_id)
        self._refuse_if_issued(quote)
        option = await self._option(quote, option_id)
        fields = payload.model_dump(exclude_unset=True)
        recommended = fields.pop("is_recommended", None)
        for name, value in fields.items():
            if value is None and name in _NOT_NULLABLE:
                continue
            setattr(option, name, value)
        if recommended is True:
            await self._make_sole_recommendation(quote.id, option.id)
        elif recommended is False:
            option.is_recommended = False
        await self.db.commit()
        return option

    async def remove_option(self, quote_id: uuid.UUID, option_id: uuid.UUID) -> None:
        quote = await self._load(quote_id)
        self._refuse_if_issued(quote)
        option = await self._option(quote, option_id)
        await self.db.delete(option)
        await self.db.commit()

    async def _make_sole_recommendation(
        self, quote_id: uuid.UUID, option_id: uuid.UUID
    ) -> None:
        rows = (
            (
                await self.db.execute(
                    select(QuoteOption).where(QuoteOption.quote_id == quote_id)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.is_recommended = row.id == option_id


    async def add_rejected_candidate(
        self, quote_id: uuid.UUID, payload: RejectedCandidateIn
    ) -> QuoteRejectedCandidate:
        quote = await self._load(quote_id)
        self._refuse_if_issued(quote)
        if payload.accommodation_id is not None:
            accommodation = await self.db.get(Accommodation, payload.accommodation_id)
            if accommodation is None:
                raise NotFoundError("Accommodation not found.")
            if any(
                o.accommodation_id == payload.accommodation_id for o in quote.options
            ):
                raise AppError(
                    f"{accommodation.name} is offered as an option on this quote, so "
                    f"it cannot also be listed as considered and declined."
                )
        highest = max(
            (c.sort_order for c in quote.rejected_candidates), default=0
        )
        candidate = QuoteRejectedCandidate(
            quote_id=quote.id,
            accommodation_id=payload.accommodation_id,
            name=payload.name,
            reason=payload.reason,
            sort_order=payload.sort_order or highest + 1,
            source="manual",
        )
        self.db.add(candidate)
        await self.db.commit()
        return candidate

    async def remove_rejected_candidate(
        self, quote_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> None:
        quote = await self._load(quote_id)
        self._refuse_if_issued(quote)
        candidate = next(
            (c for c in quote.rejected_candidates if c.id == candidate_id), None
        )
        if candidate is None:
            raise NotFoundError("Rejected candidate not found on this quote.")
        if candidate.source != "manual":
            raise AppError(
                "That refusal came from the rates, not from a person — the property "
                "does not meet its own minimum stay for these dates. Change the "
                "dates or the property's rates; deleting the line would only hide "
                "it until the next re-price."
            )
        await self.db.delete(candidate)
        await self.db.commit()


    async def readiness(self, quote_id: uuid.UUID) -> Readiness:
        quote = await self._load(quote_id)
        cfg = await PricingConfigService(self.db).get()
        try:
            priced = await OptionPricingService(self.db).compute(quote)
        except AppError as exc:
            return Readiness(
                is_ready=False,
                catered_options=0,
                self_catering_options=0,
                problems=[Problem(BLOCKING, "not_priceable", str(exc))],
            )
        sequenced = await self._sequenced(quote, cfg)
        return self._grade(
            quote,
            priced,
            cfg,
            sequencing=self._sequence_problems(quote, sequenced),
        )

    def _grade(
        self,
        quote: Quote,
        priced: OptionPricingResult,
        cfg: PricingConfig,
        *,
        sequencing: list[Problem] | None = None,
    ) -> Readiness:
        problems: list[Problem] = []

        for warning in priced.warnings:
            problems.append(Problem(BLOCKING, "unpriced_option", warning))

        catered = [o for o in priced.options if not needs_chef(o.meal_plan_code)]
        self_catering = [o for o in priced.options if needs_chef(o.meal_plan_code)]

        for option in self_catering:
            missing_chef = "chef" not in option.components
            missing_food = "meals" not in option.components
            if missing_chef or missing_food:
                needs = " and ".join(
                    label
                    for present, label in (
                        (missing_chef, "a chef fee"),
                        (missing_food, "a food cost"),
                    )
                    if present
                )
                problems.append(
                    Problem(
                        BLOCKING,
                        "missing_meal_cost",
                        f"{option.accommodation_name} is priced on "
                        f"{option.meal_plan_code}, so it needs {needs}. Without "
                        f"it the option is under-priced by the cost of feeding "
                        f"the group.",
                    )
                )

        recommended = [o for o in quote.options if o.is_recommended]
        if not recommended:
            problems.append(
                Problem(
                    BLOCKING,
                    "no_recommendation",
                    "No option is flagged as recommended. The document leads on the "
                    "recommendation, and the engine does not choose between hotels.",
                )
            )
        elif len(recommended) > 1:
            problems.append(
                Problem(
                    BLOCKING,
                    "multiple_recommendations",
                    f"{len(recommended)} options are flagged as recommended; the "
                    f"document can only lead on one.",
                )
            )
        elif not any(o.option_id == recommended[0].id for o in priced.options):
            problems.append(
                Problem(
                    BLOCKING,
                    "recommendation_not_priced",
                    "The recommended property is not among the priced options, so "
                    "the document would lead on a property with no price.",
                )
            )

        problems.extend(
            self._count_problems(
                len(catered),
                cfg.min_catered_options,
                cfg.max_catered_options,
                label="catered",
                noun="hotel option",
            )
        )
        problems.extend(
            self._count_problems(
                len(self_catering),
                cfg.min_self_catering_options,
                cfg.max_self_catering_options,
                label="self_catering",
                noun="self-catering option",
            )
        )

        problems.extend(self._package_problems(quote))
        problems.extend(self._transport_problems(quote, priced))
        problems.extend(self._itinerary_problems(quote, priced))
        problems.extend(sequencing or [])

        return Readiness(
            is_ready=not any(p.severity == BLOCKING for p in problems),
            catered_options=len(catered),
            self_catering_options=len(self_catering),
            problems=problems,
        )

    @staticmethod
    def _package_problems(quote: Quote) -> list[Problem]:
        out: list[Problem] = []
        for option in sorted(quote.options, key=lambda o: o.sort_order):
            if not option.legs:
                continue
            for found in check_package(
                [
                    Leg(
                        sequence=leg.sequence,
                        destination=str(leg.destination_id),
                        check_in=leg.check_in,
                        check_out=leg.check_out,
                    )
                    for leg in option.legs
                ],
                arrival=quote.arrival_date,
                departure=quote.departure_date,
            ):
                out.append(
                    Problem(
                        BLOCKING if found.blocking else ADVISORY,
                        found.code,
                        f"Option {option.sort_order}: {found.message}",
                    )
                )
        return out

    async def _destination_names(
        self, priced: OptionPricingResult
    ) -> dict[uuid.UUID, str]:
        wanted = {leg.destination_id for option in priced.options for leg in option.legs}
        if not wanted:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(Destination).where(Destination.id.in_(wanted))
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row.name for row in rows}

    async def _blurbs(self, priced: OptionPricingResult) -> dict[uuid.UUID, str]:
        wanted = {option.accommodation_id for option in priced.options}
        wanted |= {leg.accommodation_id for option in priced.options for leg in option.legs}
        if not wanted:
            return {}
        narratives = NarrativeService(self.db)
        out: dict[uuid.UUID, str] = {}
        for accommodation_id in wanted:
            approved = await narratives.printable(ACCOMMODATION, accommodation_id)
            if approved is not None:
                out[accommodation_id] = approved.text
                continue
            row = await self.db.get(Accommodation, accommodation_id)
            text = (row.blurb or row.description) if row is not None else None
            if text:
                out[accommodation_id] = text
        return out

    async def _residence_labels(self) -> dict[str, str]:
        rows = (await self.db.execute(select(ResidenceCategory))).scalars().all()
        return {row.key: row.name for row in rows}

    @staticmethod
    def _transport_problems(
        quote: Quote, priced: OptionPricingResult
    ) -> list[Problem]:
        out: list[Problem] = []
        legs = max(
            [len(option.legs) for option in quote.options if option.legs] or [1]
        )
        for found in check_transport(segments_of(quote.transport_segments), legs=legs):
            out.append(
                Problem(
                    BLOCKING if found.blocking else ADVISORY,
                    found.code,
                    found.message,
                )
            )
        for found in priced.transport.problems:
            out.append(
                Problem(
                    BLOCKING if found.blocking else ADVISORY,
                    found.code,
                    found.message,
                )
            )
        for movement in priced.transport.unpriced:
            out.append(
                Problem(
                    BLOCKING,
                    "unpriced_transport",
                    f"{movement} has no tariff on file, so every option is "
                    f"under-priced by the whole cost of that movement. Load the "
                    f"fare, or take the segment off the quote and say on the "
                    f"document that the client arranges it.",
                )
            )
        return out

    async def _sequenced(
        self, quote: Quote, cfg: PricingConfig
    ) -> dict[uuid.UUID, Sequenced]:
        routes = RouteService(self.db)
        names = await self._destination_place_names(quote)
        cache: dict[tuple[uuid.UUID, uuid.UUID], Road | None] = {}
        out: dict[uuid.UUID, Sequenced] = {}

        for option in sorted(quote.options, key=lambda o: o.sort_order):
            legs = sorted(option.legs, key=lambda leg: leg.sequence)
            if len(legs) < 2:
                continue
            ids = [leg.destination_id for leg in legs]
            by_name = {names.get(one, str(one)): one for one in ids}

            def road_for(
                here: str, there: str, *, _by_name: dict[str, uuid.UUID] = by_name
            ) -> Road | None:
                pair = (_by_name[here], _by_name[there])
                return cache.get(pair)

            for first in ids:
                for second in ids:
                    if first == second or (first, second) in cache:
                        continue
                    on = next(
                        (
                            leg.check_in
                            for leg in legs
                            if leg.destination_id == second
                        ),
                        quote.arrival_date,
                    )
                    cache[(first, second)] = await routes.find(
                        origin_id=first, destination_id=second, on=on
                    )

            out[option.id] = check_sequence(
                [names.get(one, str(one)) for one in ids],
                road_for=road_for,
                nights=[
                    (leg.check_out - leg.check_in).days for leg in legs
                ],
                max_drive_minutes=cfg.max_drive_minutes_per_day,
            )
        return out

    @staticmethod
    def _sequence_problems(
        quote: Quote, sequenced: dict[uuid.UUID, Sequenced]
    ) -> list[Problem]:
        order = {option.id: option.sort_order for option in quote.options}
        return [
            Problem(
                BLOCKING if problem.blocking else ADVISORY,
                problem.code,
                f"Option {order.get(option_id, 0)}: {problem.message}",
            )
            for option_id, result in sequenced.items()
            for problem in result.problems
        ]

    async def _destination_place_names(self, quote: Quote) -> dict[uuid.UUID, str]:
        wanted = {
            leg.destination_id for option in quote.options for leg in option.legs
        }
        if not wanted:
            return {}
        rows = (
            (
                await self.db.execute(
                    select(Destination).where(Destination.id.in_(wanted))
                )
            )
            .scalars()
            .all()
        )
        return {row.id: row.name for row in rows}

    @staticmethod
    def _movements(
        quote: Quote, roads: Mapping[int, Road] | None = None
    ) -> list[Movement]:
        return [
            Movement(
                sequence=segment.sequence,
                kind=segment.kind,
                mode=segment.mode,
                label=segment.description or f"{segment.mode.upper()} {segment.kind}",
                on=segment.travel_date,
                is_optional=segment.is_optional,
                duration_minutes=(
                    road.drive_time_minutes
                    if (road := (roads or {}).get(segment.sequence)) is not None
                    else None
                ),
            )
            for segment in sorted(
                quote.transport_segments, key=lambda one: one.sequence
            )
        ]

    def _itinerary_problems(
        self, quote: Quote, priced: OptionPricingResult
    ) -> list[Problem]:
        return [
            Problem(
                BLOCKING if found.blocking else ADVISORY,
                found.code,
                found.message,
            )
            for found in check_itinerary(
                arrival=quote.arrival_date,
                departure=quote.departure_date,
                movements=self._movements(quote),
                excursions=priced.activities.scheduled,
            )
        ]

    @staticmethod
    def _count_problems(
        found: int, minimum: int, maximum: int, *, label: str, noun: str
    ) -> list[Problem]:
        if found > maximum:
            return [
                Problem(
                    BLOCKING,
                    f"too_many_{label}_options",
                    f"{found} {noun}s; the document is built for at most {maximum}.",
                )
            ]
        if found < minimum:
            return [
                Problem(
                    ADVISORY,
                    f"few_{label}_options",
                    f"{found} {noun}s; {minimum} to {maximum} gives the client a real "
                    f"choice.",
                )
            ]
        return []


    async def issue(
        self, quote_id: uuid.UUID, *, actor_id: uuid.UUID | None
    ) -> QuoteVersion:
        quote = await self._load(quote_id)
        cfg = await PricingConfigService(self.db).get()
        priced = await OptionPricingService(self.db).price_options(quote_id)
        quote = await self._load(quote_id)
        await self.db.refresh(quote, ["options", "rejected_candidates"])

        sequenced = await self._sequenced(quote, cfg)
        readiness = self._grade(
            quote,
            priced,
            cfg,
            sequencing=self._sequence_problems(quote, sequenced),
        )
        blocking = [p for p in readiness.problems if p.severity == BLOCKING]
        if blocking:
            raise AppError(
                "This quote is not ready to issue: "
                + " ".join(f"({p.code}) {p.message}" for p in blocking)
            )

        recommended_option = next(o for o in quote.options if o.is_recommended)
        headline = next(
            o for o in priced.options if o.option_id == recommended_option.id
        )

        next_number = (
            await self.db.execute(
                select(func.coalesce(func.max(QuoteVersion.version_number), 0) + 1).where(
                    QuoteVersion.quote_id == quote_id
                )
            )
        ).scalar_one()

        version = QuoteVersion(
            quote_id=quote.id,
            version_number=int(next_number),
            snapshot=_snapshot(
                quote,
                priced,
                readiness,
                destinations=await self._destination_names(priced),
                residences=await self._residence_labels(),
                driving=sequenced,
                blurbs=await self._blurbs(priced),
            ),
            currency=headline.currency,
            created_by=actor_id,
            **_headline_money(headline),
        )
        options_by_id = {o.id: o for o in quote.options}
        for order, costing in enumerate(priced.options, start=1):
            option = options_by_id[costing.option_id]
            version.options.append(
                QuoteVersionOption(
                    option_id=option.id,
                    accommodation_id=costing.accommodation_id,
                    accommodation_name=costing.accommodation_name,
                    meal_plan_label=costing.meal_plan_name,
                    rooms_required=costing.rooms_required,
                    cost_subtotal=costing.build_up.cost_subtotal,
                    contingency_value=costing.build_up.contingency_value,
                    profit_value=costing.build_up.profit_value,
                    agent_cover_fee=costing.build_up.agent_cover_fee,
                    supplier_paid_total=costing.supplier_paid_total,
                    retained_discount=costing.retained_discount,
                    selling_total=costing.client_total,
                    per_person=costing.build_up.per_person,
                    currency=costing.currency,
                    is_recommended=option.is_recommended,
                    is_comparable=costing.is_comparable,
                    sort_order=option.sort_order or order,
                )
            )
        self.db.add(version)
        await self.db.flush()

        quote.current_version_id = version.id
        quote.valid_until = date.today() + timedelta(days=cfg.quotation_validity_days)
        quote.status = "sent"
        await self.db.commit()
        return (
            await self.db.execute(select(QuoteVersion).where(QuoteVersion.id == version.id))
        ).scalar_one()

    async def select_option(self, quote_id: uuid.UUID, option_id: uuid.UUID) -> Quote:
        quote = await self._load(quote_id)
        await self._option(quote, option_id)
        quote.selected_option_id = option_id
        quote.selected_at = datetime.now(UTC)
        await self.db.commit()
        return await self._load(quote_id)

    async def record_outcome(
        self,
        quote_id: uuid.UUID,
        *,
        outcome: str,
        actor_id: uuid.UUID | None,
        option_id: uuid.UUID | None = None,
        note: str | None = None,
        today: date | None = None,
    ) -> Quote:
        quote = await self._load(quote_id)
        try:
            check_outcome(
                quote.status,
                quote.valid_until,
                outcome=outcome,
                today=today or date.today(),
            )
        except OutcomeRefused as exc:
            raise AppError(str(exc)) from exc

        if outcome == ACCEPTED:
            chosen = option_id or quote.selected_option_id
            if chosen is None:
                raise AppError(
                    "Say which option the client accepted. A quote offers "
                    "several, so an acceptance without one leaves the booking "
                    "and the revenue figure undecided."
                )
            await self._option(quote, chosen)
            if quote.selected_option_id != chosen:
                quote.selected_option_id = chosen
                quote.selected_at = datetime.now(UTC)

        quote.status = outcome
        quote.decided_at = datetime.now(UTC)
        quote.decided_by = actor_id
        quote.decision_note = note
        await self.db.commit()
        return await self._load(quote_id)

    async def conversion(
        self,
        *,
        since: date | None = None,
        until: date | None = None,
        today: date | None = None,
    ) -> Conversion:
        stmt = (
            select(Quote, QuoteVersion, QuoteOption)
            .outerjoin(QuoteVersion, QuoteVersion.id == Quote.current_version_id)
            .outerjoin(QuoteOption, QuoteOption.id == Quote.selected_option_id)
            .where(Quote.status != DRAFT)
        )
        if since is not None:
            stmt = stmt.where(Quote.created_at >= _start_of(since))
        if until is not None:
            stmt = stmt.where(Quote.created_at < _start_of(until + timedelta(days=1)))
        rows = list((await self.db.execute(stmt)).all())

        decided: list[Decided] = []
        for quote, version, option in rows:
            decided.append(
                Decided(
                    status=quote.status,
                    currency=(
                        version.currency
                        if version is not None
                        else quote.presentation_currency
                    ),
                    value=version.selling_price if version is not None else None,
                    valid_until=quote.valid_until,
                    issued_on=(
                        version.created_at.date() if version is not None else None
                    ),
                    decided_on=(
                        quote.decided_at.date() if quote.decided_at else None
                    ),
                    took_recommendation=(
                        bool(option.is_recommended) if option is not None else None
                    ),
                )
            )
        return convert(decided, today=today or date.today())


    def _refuse_if_issued(self, quote: Quote) -> None:
        if quote.status != "draft":
            raise AppError(
                f"This quote is {quote.status}, not a draft. Editing the options of a "
                f"quote already sent would make the client's copy disagree with ours "
                f"— re-issue it instead, which appends a new version."
            )

    async def _load(self, quote_id: uuid.UUID) -> Quote:
        quote = (
            await self.db.execute(select(Quote).where(Quote.id == quote_id))
        ).scalar_one_or_none()
        if quote is None:
            raise NotFoundError("Quote not found.")
        return quote

    @staticmethod
    async def _option(quote: Quote, option_id: uuid.UUID) -> QuoteOption:
        option = next((o for o in quote.options if o.id == option_id), None)
        if option is None:
            raise NotFoundError("Option not found on this quote.")
        return option


def _start_of(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _headline_money(headline: OptionCosting) -> dict[str, Decimal]:
    selling = _money(headline.client_total)
    internal = _money(headline.build_up.cost_subtotal - headline.retained_discount)
    profit = selling - internal
    return {
        "internal_cost": internal,
        "selling_price": selling,
        "gross_profit": profit,
        "gross_margin": (
            (profit / selling).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            if selling
            else Decimal(0)
        ),
    }


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _driving(sequenced: Sequenced | None) -> dict | None:
    if sequenced is None:
        return None
    score = sequenced.score
    return {
        "total_km": str(score.total_km),
        "total_minutes": score.total_minutes,
        "longest_minutes": score.longest_minutes,
        "unknown_hops": score.unknown_hops,
        "hops": score.hops,
        "better_order": list(sequenced.better_order),
        "saving_km": str(sequenced.saving_km),
    }


def _snapshot(
    quote: Quote,
    priced: OptionPricingResult,
    readiness: Readiness,
    *,
    destinations: dict[uuid.UUID, str] | None = None,
    residences: dict[str, str] | None = None,
    driving: dict[uuid.UUID, Sequenced] | None = None,
    blurbs: dict[uuid.UUID, str] | None = None,
) -> dict:
    recommended = {o.id: o.is_recommended for o in quote.options}
    order = {o.id: o.sort_order for o in quote.options}
    destinations = destinations or {}
    residences = residences or {}
    movements = QuoteAssemblyService._movements(quote, priced.transport.roads)
    driving = driving or {}
    blurbs = blurbs or {}
    return {
        "quote_number": quote.quote_number,
        "currency": quote.presentation_currency.upper(),
        "arrival_date": quote.arrival_date.isoformat(),
        "departure_date": quote.departure_date.isoformat(),
        "pax_count": priced.pax or quote.pax_count,
        "options": [
            {
                "option_id": str(o.option_id),
                "accommodation_id": str(o.accommodation_id),
                "accommodation_name": o.accommodation_name,
                "room_type_name": o.room_type_name,
                "meal_plan_code": o.meal_plan_code,
                "meal_plan_name": o.meal_plan_name,
                "meal_plan_fallback_from": o.meal_plan_fallback_from,
                "rooms_required": o.rooms_required,
                "nights": o.nights,
                "is_comparable": o.is_comparable,
                "is_recommended": recommended.get(o.option_id, False),
                "sort_order": order.get(o.option_id, 0),
                "components": {k: str(v) for k, v in o.components.items()},
                "supplements": [
                    {
                        "label": s.label,
                        "basis": s.basis,
                        "nights": s.nights,
                        "cost": str(s.cost),
                    }
                    for s in o.supplements
                ],
                "supplier_paid_total": str(o.supplier_paid_total),
                "retained_discount": str(o.retained_discount),
                "cost_subtotal": str(o.build_up.cost_subtotal),
                "contingency_value": str(o.build_up.contingency_value),
                "profit_value": str(o.build_up.profit_value),
                "agent_cover_fee": str(o.build_up.agent_cover_fee),
                "per_person": (
                    str(o.build_up.per_person)
                    if o.build_up.per_person is not None
                    else None
                ),
                "group_total": str(o.build_up.group_total),
                "client_total": str(o.client_total),
                "warnings": list(o.warnings),
                "activities": list(o.activities),
                "legs": [
                    {
                        "sequence": leg.sequence,
                        "accommodation_name": leg.accommodation_name,
                        "destination_name": destinations.get(leg.destination_id, ""),
                        "room_type_name": leg.room.room_type_name,
                        "meal_plan_code": leg.plan_code,
                        "meal_plan_name": leg.plan.name,
                        "rooms_required": leg.room.rooms,
                        "nights": leg.nights,
                        "meal_plan_fallback_from": (
                            leg.requested_plan if leg.is_fallback else None
                        ),
                    }
                    for leg in o.legs
                ],
                "blurb": blurbs.get(o.accommodation_id),
                "driving": _driving(driving.get(o.option_id)),
                "days": [
                    {
                        "number": day.number,
                        "date": day.on.isoformat(),
                        "destination": day.destination,
                        "property_name": day.property_name,
                        "board": day.board,
                        "leg": day.leg,
                        "moves_from": day.moves_from,
                        "movements": [
                            {
                                "label": one.label,
                                "minutes": one.duration_minutes,
                            }
                            for one in day.movements
                        ],
                        "excursions": list(day.excursions),
                        "is_arrival": day.is_arrival,
                        "is_departure": day.is_departure,
                        "has_night": day.has_night,
                    }
                    for day in build_programme(
                        [
                            Leg(
                                sequence=leg.sequence,
                                destination=destinations.get(leg.destination_id, ""),
                                check_in=leg.check_in,
                                check_out=leg.check_out,
                                property_name=leg.accommodation_name,
                                board=leg.plan_code,
                            )
                            for leg in o.legs
                        ],
                        arrival=quote.arrival_date,
                        departure=quote.departure_date,
                        movements=movements,
                        excursions=priced.activities.scheduled,
                    )
                ],
                "cohorts": [
                    {
                        "residence": price.cohort.residence,
                        "residence_label": residences.get(
                            price.cohort.residence, price.cohort.residence
                        ),
                        "traveller_type": price.cohort.traveller_type,
                        "headcount": price.cohort.count,
                        "currency": price.currency,
                        "per_person": str(price.per_person),
                        "total": str(price.total),
                    }
                    for price in (o.cohort_prices.cohorts if o.cohort_prices else ())
                ],
                "lines": [
                    {
                        "label": entry.label,
                        "component": entry.component,
                        "basis": entry.basis,
                        "unit_amount": str(entry.unit_amount),
                        "quantity": entry.quantity,
                        "currency": entry.currency,
                        "extended": str(entry.extended),
                        "source": entry.source,
                        "residence": entry.residence,
                        "traveller_type": entry.traveller_type,
                        "leg": entry.leg,
                        "sheet_amount": (
                            str(entry.sheet_amount)
                            if entry.sheet_amount is not None
                            else None
                        ),
                        "paid_amount": (
                            str(entry.paid_amount)
                            if entry.paid_amount is not None
                            else None
                        ),
                    }
                    for entry in o.entries
                ],
                "conversions": {
                    pair: str(rate)
                    for pair, rate in (
                        o.cohort_prices.conversions if o.cohort_prices else {}
                    ).items()
                },
            }
            for o in priced.options
        ],
        "transport": {
            "total": str(priced.transport.total),
            "optional_total": str(priced.transport.optional_total),
            "optional_price": str(priced.transport.optional_price),
            "named": list(priced.transport.named),
            "movements": [
                {
                    "sequence": charge.sequence,
                    "kind": charge.kind,
                    "mode": charge.mode,
                    "label": charge.label,
                    "basis": charge.basis,
                    "units": charge.units,
                    "unit_amount": str(charge.unit_amount),
                    "currency": charge.currency,
                    "cost": str(charge.cost),
                    "is_optional": charge.is_optional,
                    "is_vvip": charge.is_vvip,
                }
                for charge in (
                    priced.transport.charges + priced.transport.optional
                )
            ],
        },
        "rejected": [
            {
                "accommodation_id": (
                    str(r.accommodation_id) if r.accommodation_id else None
                ),
                "name": r.name,
                "reason": r.reason,
                "source": r.source,
            }
            for r in sorted(quote.rejected_candidates, key=lambda r: r.sort_order)
        ],
        "readiness": {
            "catered_options": readiness.catered_options,
            "self_catering_options": readiness.self_catering_options,
            "problems": [
                {"severity": p.severity, "code": p.code, "message": p.message}
                for p in readiness.problems
            ],
        },
    }
