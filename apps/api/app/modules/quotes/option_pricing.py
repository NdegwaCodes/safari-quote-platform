from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.vat import to_vat_inclusive
from app.modules.accommodations.models import (
    Accommodation,
    AccommodationRate,
    AccommodationSupplement,
    MealPlan,
    RoomType,
)
from app.modules.activities.models import Activity, ActivityRate
from app.modules.currency.fx import AdminExchangeRateProvider
from app.modules.park_fees.models import ParkFee
from app.modules.pricing.service import PricingConfigService
from app.modules.quotes import routing
from app.modules.quotes import transport as transport_rules
from app.modules.quotes.cohorts import (
    CostLine,
    Group,
    GroupPrice,
    multiplier,
    price_group,
)
from app.modules.quotes.group import build_group, residence_ids
from app.modules.quotes.itinerary import Excursion
from app.modules.quotes.models import (
    Quote,
    QuoteOption,
    QuoteRejectedCandidate,
    QuoteTransportSegment,
)
from app.modules.quotes.options import (
    BuildUp,
    build_up,
    costed_rate,
    default_chef_fee_per_meal,
    meals_needing_chef,
    meets_minimum_stay,
    minimum_stay_reason,
    needs_chef,
    rate_for_occupancy,
    resolve_meal_plan,
    room_plan,
    stay_nights,
    supplement_cost,
    supplier_paid,
)
from app.modules.quotes.packages import Leg, Problem, nights_of
from app.modules.quotes.routing import Road
from app.modules.transport.models import DestinationTransportMode, TransferRate
from app.modules.transport.service import RouteService
from app.modules.vehicles.models import Vehicle
from app.modules.vehicles.service import FuelPriceService, compute_transport_cost


@dataclass(frozen=True)
class CostEntry:

    label: str
    component: str
    basis: str
    unit_amount: Decimal
    quantity: int
    currency: str
    extended: Decimal
    source: str
    residence: str | None = None
    traveller_type: str | None = None
    leg: int | None = None
    sheet_amount: Decimal | None = None
    paid_amount: Decimal | None = None


@dataclass(frozen=True)
class SupplementCharge:

    label: str
    kind: str
    basis: str
    amount: Decimal
    currency: str
    nights: int
    cost: Decimal
    units: int = 1
    source: str = ""


@dataclass(frozen=True)
class TransportCharge:

    sequence: int
    kind: str
    mode: str
    label: str
    basis: str
    units: int
    unit_amount: Decimal
    currency: str
    cost: Decimal
    is_optional: bool = False
    is_vvip: bool = False
    source: str = ""


@dataclass
class TransportCosting:

    total: Decimal = Decimal(0)
    optional_total: Decimal = Decimal(0)
    lines: list[CostLine] = field(default_factory=list)
    charges: list[TransportCharge] = field(default_factory=list)
    optional: list[TransportCharge] = field(default_factory=list)
    named: list[str] = field(default_factory=list)
    unpriced: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entries: list[CostEntry] = field(default_factory=list)
    optional_price: Decimal = Decimal(0)
    roads: dict[int, Road] = field(default_factory=dict)
    problems: list[Problem] = field(default_factory=list)


@dataclass
class ActivityCosting:

    total: Decimal = Decimal(0)
    lines: list[CostLine] = field(default_factory=list)
    entries: list[CostEntry] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    scheduled: list[Excursion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RoomTypeQuote:

    room_type_id: uuid.UUID
    room_type_name: str
    rooms: int
    room_plan: list[int]
    costed_total: Decimal
    paid_total: Decimal
    retained_discount: Decimal
    derived_occupancies: tuple[int, ...] = ()
    warnings: list[str] = field(default_factory=list)
    entries: list[CostEntry] = field(default_factory=list)
    costed_by_residence: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    child_by_residence: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    children_priced: frozenset[str] = frozenset()


@dataclass
class LegCosting:

    sequence: int
    accommodation_id: uuid.UUID
    accommodation_name: str
    destination_id: uuid.UUID
    check_in: date
    check_out: date
    room: RoomTypeQuote
    plan: MealPlan
    plan_code: str
    requested_plan: str
    is_fallback: bool
    nights: int
    components: dict[str, Decimal]
    supplements: list[SupplementCharge]
    park_lines: list[CostLine]
    warnings: list[str] = field(default_factory=list)
    entries: list[CostEntry] = field(default_factory=list)


@dataclass
class OptionCosting:

    option_id: uuid.UUID
    accommodation_id: uuid.UUID
    accommodation_name: str
    room_type_id: uuid.UUID
    room_type_name: str
    meal_plan_id: uuid.UUID
    meal_plan_code: str
    meal_plan_name: str
    meal_plan_fallback_from: str | None
    rooms_required: int
    nights: int
    currency: str
    components: dict[str, Decimal]
    supplements: list[SupplementCharge]
    supplier_paid_total: Decimal
    retained_discount: Decimal
    build_up: BuildUp
    is_comparable: bool
    warnings: list[str] = field(default_factory=list)
    cohort_prices: GroupPrice | None = None
    entries: list[CostEntry] = field(default_factory=list)
    legs: list[LegCosting] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)

    @property
    def client_total(self) -> Decimal:
        if self.cohort_prices is not None:
            return self.cohort_prices.group_total
        return self.build_up.group_total


CHILD = "child"

ROOM_BEARERS = ("adult", "infant")


def _children_per_room(children: int, rooms: int) -> list[int]:
    if rooms <= 0:
        return []
    base, extra = divmod(max(0, children), rooms)
    return [base + (1 if index < extra else 0) for index in range(rooms)]


PARK_ENTRY = "park_entry"


def _rate_source(rate: AccommodationRate) -> str:
    parts = [
        f"accommodation_rates {rate.id}",
        f"{rate.rate_kind.upper()} · {rate.season_name} from {rate.effective_from}",
    ]
    if rate.supplier_discount_pct:
        parts.append(f"sheet discount {rate.supplier_discount_pct}%")
    if rate.source_document_id is not None:
        parts.append(f"document {rate.source_document_id}")
    return " · ".join(parts)


def _supersedes(
    candidate: AccommodationRate, current: AccommodationRate, presentation: str
) -> bool:
    matches = candidate.currency.upper() == presentation
    already = current.currency.upper() == presentation
    if matches != already:
        return matches
    return candidate.effective_from > current.effective_from


@dataclass(frozen=True)
class RejectedOption:

    accommodation_id: uuid.UUID
    name: str
    reason: str


@dataclass
class OptionPricingResult:
    options: list[OptionCosting] = field(default_factory=list)
    rejected: list[RejectedOption] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    transport: TransportCosting = field(default_factory=lambda: TransportCosting())
    activities: ActivityCosting = field(default_factory=lambda: ActivityCosting())
    pax: int = 0


class OptionPricingService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.fx = AdminExchangeRateProvider(db)


    async def compute(self, quote: Quote) -> OptionPricingResult:
        if not quote.options:
            raise AppError(
                "This quote has no options to price. Add the properties to offer "
                "before pricing."
            )
        nights = stay_nights(quote.arrival_date, quote.departure_date)
        group = await build_group(self.db, quote)
        requested_plan = await self._requested_plan_code(quote)
        cfg = await PricingConfigService(self.db).get()
        contingency = (
            quote.contingency_pct
            if quote.contingency_pct is not None
            else cfg.contingency_pct
        )
        profit = quote.profit_pct if quote.profit_pct is not None else cfg.profit_pct
        transport = await self._transport(quote, group=group)
        activities = await self._activities(quote, group=group)
        if transport.optional_total:
            transport.optional_price = build_up(
                components={"transport": transport.optional_total},
                pax=group.pax,
                contingency_pct=contingency,
                profit_pct=profit,
                rounding_step=cfg.rounding_for(quote.presentation_currency),
                uniform_group=group.is_uniform,
            ).group_total

        result = OptionPricingResult(
            transport=transport, activities=activities, pax=group.pax
        )
        for option in sorted(quote.options, key=lambda o: o.sort_order):
            await self._price_one(
                quote,
                option,
                nights=nights,
                group=group,
                requested_plan=requested_plan,
                contingency_pct=contingency,
                profit_pct=profit,
                rounding=cfg.rounding_for,
                chef_fee_per_day=cfg.default_chef_fee_per_day,
                chef_covers=cfg.default_chef_covers,
                transport=transport,
                activities=activities,
                into=result,
            )
        return result

    async def price_options(self, quote_id: uuid.UUID) -> OptionPricingResult:
        quote = await self._load(quote_id)
        result = await self.compute(quote)

        by_option = {c.option_id: c for c in result.options}
        for option in quote.options:
            costing = by_option.get(option.id)
            if costing is None:
                continue
            option.room_type_id = costing.room_type_id
            option.meal_plan_id = costing.meal_plan_id
            option.rooms_required = costing.rooms_required
            option.meal_plan_fallback_from = costing.meal_plan_fallback_from
            option.is_comparable = costing.is_comparable
            per_sequence = {one.sequence: one for one in costing.legs}
            for leg in option.legs:
                resolved = per_sequence.get(leg.sequence)
                if resolved is None:
                    continue
                leg.room_type_id = resolved.room.room_type_id
                leg.meal_plan_id = resolved.plan.id
                leg.rooms_required = resolved.room.rooms
                leg.meal_plan_fallback_from = (
                    resolved.requested_plan if resolved.is_fallback else None
                )

        stale = (
            (
                await self.db.execute(
                    select(QuoteRejectedCandidate).where(
                        QuoteRejectedCandidate.quote_id == quote.id,
                        QuoteRejectedCandidate.source == "engine",
                    )
                )
            )
            .scalars()
            .all()
        )
        for previous in stale:
            await self.db.delete(previous)
        for order, refused in enumerate(result.rejected, start=1):
            self.db.add(
                QuoteRejectedCandidate(
                    quote_id=quote.id,
                    accommodation_id=refused.accommodation_id,
                    name=refused.name,
                    reason=refused.reason,
                    sort_order=order,
                    source="engine",
                )
            )
        await self.db.commit()
        return result


    async def _price_leg(
        self,
        quote: Quote,
        option: QuoteOption,
        *,
        accommodation_id: uuid.UUID,
        nights: list[date],
        group: Group,
        requested_plan: str,
        sequence: int,
        chef_fee_per_day: Decimal,
        chef_covers: int,
        into: OptionPricingResult,
    ) -> LegCosting | None:
        pax = group.pax
        accommodation = await self.db.get(Accommodation, accommodation_id)
        if accommodation is None:
            raise NotFoundError(
                "An option references an accommodation that no longer exists."
            )

        rates = await self._rates(quote, accommodation.id, nights, group)
        if not rates:
            into.warnings.append(
                f"{accommodation.name}: no rates are loaded for "
                f"{nights[0]} to {nights[-1]} for "
                f"{' or '.join(group.residences)}, so it could not be priced."
            )
            return None

        by_residence: dict[str, set[str]] = {}
        for (_room, code, residence) in rates:
            by_residence.setdefault(residence, set()).add(code)
        available = set.intersection(*by_residence.values()) if by_residence else set()
        if not available and len(group.residences) > 1:
            into.warnings.append(
                f"{accommodation.name}: no meal plan has a rate for every "
                f"residency on this quote ("
                + "; ".join(
                    f"{res}: {'/'.join(sorted(codes))}"
                    for res, codes in sorted(by_residence.items())
                )
                + "), so it could not be priced for this group."
            )
            return None
        plan_code, is_fallback = resolve_meal_plan(requested_plan, available)
        if plan_code is None:
            into.warnings.append(
                f"{accommodation.name}: no rate on any plan in the "
                f"{requested_plan} fallback chain, so it could not be priced."
            )
            return None
        plan = await self._plan_by_code(plan_code)

        best: RoomTypeQuote | None = None
        shortfalls: list[int] = []
        room_type_ids = {room for (room, code, _res) in rates if code == plan_code}
        for room_type_id in room_type_ids:
            attempt = await self._price_room_type(
                quote,
                room_type_id,
                {
                    residence: rates[(room_type_id, plan_code, residence)]
                    for residence in group.residences
                    if (room_type_id, plan_code, residence) in rates
                },
                nights=nights,
                group=group,
            )
            if attempt is None:
                continue
            candidate, shortfall = attempt
            if shortfall is not None:
                shortfalls.append(shortfall)
                continue
            assert candidate is not None
            if best is None or candidate.costed_total < best.costed_total:
                best = candidate

        if best is None:
            if shortfalls:
                into.rejected.append(
                    RejectedOption(
                        accommodation_id=accommodation.id,
                        name=accommodation.name,
                        reason=minimum_stay_reason(len(nights), min(shortfalls)),
                    )
                )
            else:
                uncovered = [
                    night
                    for night in nights
                    if not any(
                        night in per_night
                        for (room, code, _res), per_night in rates.items()
                        if code == plan_code
                    )
                ]
                if uncovered:
                    into.warnings.append(
                        f"{accommodation.name}: no {plan_code} rate is loaded for "
                        f"{', '.join(str(night) for night in uncovered)} — a gap "
                        f"between season windows, not a capacity problem. The "
                        f"property is priceable either side of it."
                    )
                else:
                    into.warnings.append(
                        f"{accommodation.name}: no room type could house {pax} "
                        f"guests at the rates on file, so it could not be priced."
                    )
            return None

        supplements = await self._supplements(
            quote,
            accommodation.id,
            room_type_id=best.room_type_id,
            meal_plan_id=plan.id,
            nights=nights,
            pax=pax,
            rooms=best.rooms,
        )

        components: dict[str, Decimal] = {"accommodation": best.costed_total}
        if supplements:
            components["supplements"] = sum((s.cost for s in supplements), Decimal(0))

        warnings = list(best.warnings)
        park_total, park_warnings, park_lines, park_entries = await self._park_fees(
            quote, accommodation, nights=nights, group=group
        )
        if park_total:
            components["park_fees"] = park_total
        warnings.extend(park_warnings)
        chef_rate: Decimal | None = None
        chef_is_default = False
        if needs_chef(plan_code):
            meals = meals_needing_chef(plan_code, len(nights))
            if option.chef_fee_per_meal:
                chef_rate = option.chef_fee_per_meal
            else:
                chef_rate = default_chef_fee_per_meal(
                    pax, plan_code, per_day=chef_fee_per_day, covers=chef_covers
                )
                chef_is_default = chef_rate is not None
            chef = (chef_rate or Decimal(0)) * meals
            food = option.manual_meal_cost or Decimal(0)
            if chef:
                components["chef"] = chef
            if food:
                components["meals"] = food
            if not chef or not food:
                warnings.append(
                    f"priced on {plan_code}, which needs a chef and a food cost "
                    f"for {meals} group meal(s); set manual_meal_cost on this "
                    f"option before issuing it"
                    if chef
                    else f"priced on {plan_code}, which needs a chef and a food "
                    f"cost for {meals} group meal(s); set chef_fee_per_meal and "
                    f"manual_meal_cost on this option before issuing it"
                )
        if is_fallback:
            warnings.append(
                f"the client asked for {requested_plan} and this property has no "
                f"{requested_plan} rate, so it is priced on {plan_code}"
            )

        entries: list[CostEntry] = [
            replace(entry, leg=sequence) for entry in best.entries
        ]
        entries.extend(
            CostEntry(
                label=charge.label,
                component="supplements",
                basis=charge.basis,
                unit_amount=charge.amount,
                quantity=charge.units,
                currency=charge.currency,
                extended=charge.amount * charge.units,
                source=charge.source,
                leg=sequence,
            )
            for charge in supplements
        )
        entries.extend(replace(entry, leg=sequence) for entry in park_entries)
        if needs_chef(plan_code):
            meals = meals_needing_chef(plan_code, len(nights))
            if chef_rate:
                entries.append(
                    CostEntry(
                        label="Chef fee",
                        component="chef",
                        basis="per_group",
                        unit_amount=chef_rate,
                        quantity=meals,
                        currency=quote.presentation_currency.upper(),
                        extended=chef_rate * meals,
                        source=(
                            f"pricing config default_chef_fee_per_day "
                            f"(KES {chef_fee_per_day}/day per {chef_covers} guests)"
                            if chef_is_default
                            else "quote_options.chef_fee_per_meal (entered by hand)"
                        ),
                        leg=sequence,
                    )
                )
            if option.manual_meal_cost:
                entries.append(
                    CostEntry(
                        label="Group food cost",
                        component="meals",
                        basis="per_group",
                        unit_amount=option.manual_meal_cost,
                        quantity=1,
                        currency=quote.presentation_currency.upper(),
                        extended=option.manual_meal_cost,
                        source="quote_options.manual_meal_cost (entered by hand)",
                        leg=sequence,
                    )
                )

        return LegCosting(
            sequence=sequence,
            accommodation_id=accommodation.id,
            accommodation_name=accommodation.name,
            destination_id=accommodation.destination_id,
            check_in=nights[0],
            check_out=nights[-1] + timedelta(days=1),
            room=best,
            plan=plan,
            plan_code=plan_code,
            requested_plan=requested_plan,
            is_fallback=is_fallback,
            nights=len(nights),
            components=components,
            supplements=supplements,
            park_lines=park_lines,
            warnings=warnings,
            entries=entries,
        )

    async def _legs_of(
        self,
        option: QuoteOption,
        quote: Quote,
        nights: list[date],
        requested_plan: str,
    ) -> list[tuple[int, uuid.UUID, list[date], str]] | None:
        if not option.legs:
            return [(1, option.accommodation_id, nights, requested_plan)]

        plans = {
            row.id: row.code.upper()
            for row in (await self.db.execute(select(MealPlan))).scalars().all()
        }
        out: list[tuple[int, uuid.UUID, list[date], str]] = []
        for leg in sorted(option.legs, key=lambda entry: entry.sequence):
            plan = plans.get(leg.requested_meal_plan_id or uuid.UUID(int=0))
            out.append(
                (
                    leg.sequence,
                    leg.accommodation_id,
                    nights_of(
                        Leg(
                            sequence=leg.sequence,
                            destination=str(leg.destination_id),
                            check_in=leg.check_in,
                            check_out=leg.check_out,
                        )
                    ),
                    plan or requested_plan,
                )
            )
        return out


    async def _price_one(
        self,
        quote: Quote,
        option: QuoteOption,
        *,
        nights: list[date],
        group: Group,
        requested_plan: str,
        contingency_pct: Decimal,
        profit_pct: Decimal,
        rounding: Callable[[str], Decimal],
        chef_fee_per_day: Decimal,
        chef_covers: int,
        transport: TransportCosting,
        activities: ActivityCosting,
        into: OptionPricingResult,
    ) -> None:
        legs = await self._legs_of(option, quote, nights, requested_plan)
        if legs is None:
            return

        costed: list[LegCosting] = []
        for sequence, accommodation_id, leg_nights, leg_plan in legs:
            one = await self._price_leg(
                quote,
                option,
                accommodation_id=accommodation_id,
                nights=leg_nights,
                group=group,
                requested_plan=leg_plan,
                sequence=sequence,
                chef_fee_per_day=chef_fee_per_day,
                chef_covers=chef_covers,
                into=into,
            )
            if one is None:
                if len(legs) > 1:
                    into.warnings.append(
                        f"Package option {option.sort_order}: leg {sequence} "
                        f"could not be priced, so the whole package was dropped."
                    )
                return
            costed.append(one)

        lead = costed[0]
        components: dict[str, Decimal] = {}
        for one in costed:
            for label, amount in one.components.items():
                components[label] = components.get(label, Decimal(0)) + amount
        if transport.total:
            components["transport"] = transport.total
        if activities.total:
            components["activities"] = activities.total

        accommodation_lines: list[CostLine] = []
        for one in costed:
            narrowed = one.room.children_priced
            for residence, buckets in one.room.costed_by_residence.items():
                for currency, amount in buckets.items():
                    accommodation_lines.append(
                        CostLine(
                            label="accommodation",
                            amount=amount,
                            currency=currency,
                            basis="per_group",
                            residence=residence,
                            bearers=(
                                ROOM_BEARERS if residence in narrowed else ()
                            ),
                        )
                    )
            for residence, buckets in one.room.child_by_residence.items():
                for currency, amount in buckets.items():
                    accommodation_lines.append(
                        CostLine(
                            label="accommodation",
                            amount=amount,
                            currency=currency,
                            basis="per_group",
                            residence=residence,
                            traveller_type=CHILD,
                        )
                    )

        included_lines = [line for one in costed for line in one.park_lines]
        included_lines.extend(activities.lines)
        entries = [entry for one in costed for entry in one.entries]
        entries.extend(activities.entries)
        entries.extend(transport.entries)
        supplements = [charge for one in costed for charge in one.supplements]
        warnings = [
            (f"leg {one.sequence} ({one.accommodation_name}): {note}"
             if len(costed) > 1 else note)
            for one in costed
            for note in one.warnings
        ]
        warnings.extend(activities.warnings)
        warnings.extend(transport.warnings)
        paid_total = sum((one.room.paid_total for one in costed), Decimal(0))
        costed_total = sum((one.room.costed_total for one in costed), Decimal(0))

        totals = build_up(
            components=components,
            pax=group.pax,
            contingency_pct=contingency_pct,
            profit_pct=profit_pct,
            agent_cover_fee=option.agent_cover_fee,
            rounding_step=rounding(quote.presentation_currency),
            uniform_group=group.is_uniform,
        )
        cohort_prices = await self._per_cohort(
            quote,
            accommodation=accommodation_lines,
            direct_lines=included_lines + transport.lines,
            shared=components,
            capacity_of=lead.room.room_type_id,
            group=group,
            nights=nights,
            contingency_pct=contingency_pct,
            profit_pct=profit_pct,
            agent_cover_fee=option.agent_cover_fee,
            rounding=rounding,
        )
        into.options.append(
            OptionCosting(
                option_id=option.id,
                accommodation_id=lead.accommodation_id,
                accommodation_name=(
                    lead.accommodation_name
                    if len(costed) == 1
                    else " → ".join(one.accommodation_name for one in costed)
                ),
                room_type_id=lead.room.room_type_id,
                room_type_name=lead.room.room_type_name,
                meal_plan_id=lead.plan.id,
                meal_plan_code=lead.plan_code,
                meal_plan_name=lead.plan.name,
                meal_plan_fallback_from=(
                    lead.requested_plan if lead.is_fallback else None
                ),
                rooms_required=max(one.room.rooms for one in costed),
                nights=sum(one.nights for one in costed),
                currency=quote.presentation_currency.upper(),
                components=components,
                supplements=supplements,
                supplier_paid_total=paid_total,
                retained_discount=costed_total - paid_total,
                build_up=totals,
                is_comparable=(
                    option.is_comparable
                    and not any(one.is_fallback for one in costed)
                ),
                warnings=warnings,
                cohort_prices=cohort_prices,
                entries=entries,
                legs=costed,
                activities=list(activities.names),
            )
        )

    async def _price_room_type(
        self,
        quote: Quote,
        room_type_id: uuid.UUID,
        per_residence: dict[str, dict[date, dict[int, AccommodationRate]]],
        *,
        nights: list[date],
        group: Group,
    ) -> tuple[RoomTypeQuote | None, int | None] | None:
        room_type = await self.db.get(RoomType, room_type_id)
        if room_type is None or not room_type.is_active:
            return None

        sharing = self._child_sharing(
            per_residence, group, capacity=room_type.max_occupancy, nights=nights
        )
        rooming = group.rooming(
            room_type.max_occupancy,
            occupants={
                residence: group.headcount(residence)
                - group.count_of(residence, CHILD)
                for residence in sharing
            },
        )
        plan: list[int] = []
        paid: dict[str, Decimal] = {}
        costed: dict[str, Decimal] = {}
        by_residence: dict[str, dict[str, Decimal]] = {}
        child_by_residence: dict[str, dict[str, Decimal]] = {}
        derived: set[int] = set()
        per_person_basis: set[str] = set()
        used_rates: dict[tuple[uuid.UUID, int, str], list] = {}
        used_child: dict[tuple[uuid.UUID, str], list] = {}
        for residence, rooms in rooming.items():
            nightly = per_residence.get(residence)
            if not nightly:
                return None
            plan.extend(rooms)
            in_room = _children_per_room(
                group.count_of(residence, CHILD) if residence in sharing else 0,
                len(rooms),
            )
            for night in nights:
                by_occupancy = nightly.get(night)
                if not by_occupancy:
                    return None
                for index, guests in enumerate(rooms):
                    found = rate_for_occupancy(by_occupancy, guests)
                    if found is None:
                        return None
                    used, rate = found
                    if not meets_minimum_stay(len(nights), rate.min_nights):
                        assert rate.min_nights is not None
                        return None, rate.min_nights
                    if used != guests:
                        derived.add(guests)
                        if rate.single_supplement is not None:
                            per_person_basis.add(room_type.name)
                    amount = rate.rate_per_night
                    currency = rate.currency.upper()
                    paid[currency] = paid.get(currency, Decimal(0)) + supplier_paid(
                        amount, rate.supplier_discount_pct
                    )
                    charge = costed_rate(
                        amount, rate.supplier_discount_pct, rate.rate_kind
                    )
                    costed[currency] = costed.get(currency, Decimal(0)) + charge
                    mine = by_residence.setdefault(residence, {})
                    mine[currency] = mine.get(currency, Decimal(0)) + charge
                    slot = (rate.id, guests, residence)
                    if slot in used_rates:
                        used_rates[slot][0] += 1
                    else:
                        used_rates[slot] = [1, rate]

                    kids = in_room[index]
                    if not kids:
                        continue
                    assert rate.child_rate is not None
                    paid[currency] = paid.get(currency, Decimal(0)) + supplier_paid(
                        rate.child_rate, rate.supplier_discount_pct
                    ) * kids
                    child_charge = (
                        costed_rate(
                            rate.child_rate, rate.supplier_discount_pct, rate.rate_kind
                        )
                        * kids
                    )
                    costed[currency] = costed.get(currency, Decimal(0)) + child_charge
                    theirs = child_by_residence.setdefault(residence, {})
                    theirs[currency] = theirs.get(currency, Decimal(0)) + child_charge
                    cot = (rate.id, residence)
                    if cot in used_child:
                        used_child[cot][0] += kids
                    else:
                        used_child[cot] = [kids, rate]

        warnings: list[str] = []
        if derived:
            warnings.append(
                f"{room_type.name}: no rate is quoted for "
                f"{', '.join(str(o) for o in sorted(derived))}-guest occupancy, "
                f"so the next larger room's price was charged in full"
            )
        if per_person_basis:
            warnings.append(
                f"{room_type.name}: the sheet states a single supplement but no "
                f"single-occupancy rate. The room was charged in full; check "
                f"whether this sheet prices per person sharing before issuing."
            )
        entries = [
            CostEntry(
                label=f"{room_type.name}, {guests} sharing ({residence})",
                component="accommodation",
                basis="per_room_per_night",
                unit_amount=costed_rate(
                    rate.rate_per_night, rate.supplier_discount_pct, rate.rate_kind
                ),
                quantity=room_nights,
                currency=rate.currency.upper(),
                extended=costed_rate(
                    rate.rate_per_night, rate.supplier_discount_pct, rate.rate_kind
                )
                * room_nights,
                source=_rate_source(rate),
                residence=residence,
                sheet_amount=rate.rate_per_night,
                paid_amount=supplier_paid(
                    rate.rate_per_night, rate.supplier_discount_pct
                ),
            )
            for (_, guests, residence), (room_nights, rate) in used_rates.items()
        ]
        entries.extend(
            CostEntry(
                label=f"{room_type.name}, child sharing ({residence})",
                component="accommodation",
                basis="per_person_per_night",
                unit_amount=costed_rate(
                    rate.child_rate, rate.supplier_discount_pct, rate.rate_kind
                ),
                quantity=child_nights,
                currency=rate.currency.upper(),
                extended=costed_rate(
                    rate.child_rate, rate.supplier_discount_pct, rate.rate_kind
                )
                * child_nights,
                source=_rate_source(rate),
                residence=residence,
                traveller_type=CHILD,
                sheet_amount=rate.child_rate,
                paid_amount=supplier_paid(
                    rate.child_rate, rate.supplier_discount_pct
                ),
            )
            for (_, residence), (child_nights, rate) in used_child.items()
            if rate.child_rate is not None
        )
        paid_total = await self._to_presentation(quote, paid)
        costed_total = await self._to_presentation(quote, costed)
        return (
            RoomTypeQuote(
                room_type_id=room_type.id,
                room_type_name=room_type.name,
                rooms=len(plan),
                room_plan=plan,
                costed_total=costed_total,
                paid_total=paid_total,
                retained_discount=costed_total - paid_total,
                derived_occupancies=tuple(sorted(derived)),
                warnings=warnings,
                costed_by_residence=by_residence,
                child_by_residence=child_by_residence,
                children_priced=sharing,
                entries=entries,
            ),
            None,
        )

    @staticmethod
    def _child_sharing(
        per_residence: dict[str, dict[date, dict[int, AccommodationRate]]],
        group: Group,
        *,
        capacity: int,
        nights: list[date],
    ) -> frozenset[str]:
        out: set[str] = set()
        for residence in group.residences:
            children = group.count_of(residence, CHILD)
            occupants = group.headcount(residence) - children
            if not children or occupants <= 0:
                continue
            nightly = per_residence.get(residence)
            if not nightly:
                continue
            rooms = room_plan(occupants, capacity)
            stated = True
            for night in nights:
                by_occupancy = nightly.get(night)
                if not by_occupancy:
                    stated = False
                    break
                for guests in rooms:
                    found = rate_for_occupancy(by_occupancy, guests)
                    if found is None or found[1].child_rate is None:
                        stated = False
                        break
                if not stated:
                    break
            if stated:
                out.add(residence)
        return frozenset(out)


    async def _requested_plan_code(self, quote: Quote) -> str:
        if quote.requested_meal_plan_id is None:
            raise AppError(
                "Set requested_meal_plan_id on the quote before pricing options — "
                "the fallback chain has no starting point without it."
            )
        plan = await self.db.get(MealPlan, quote.requested_meal_plan_id)
        if plan is None:
            raise NotFoundError("The quote's requested meal plan no longer exists.")
        return plan.code.upper()

    async def _plan_by_code(self, code: str) -> MealPlan:
        plan = (
            await self.db.execute(select(MealPlan).where(MealPlan.code == code))
        ).scalar_one_or_none()
        if plan is None:  # pragma: no cover - the code came from a joined row
            raise NotFoundError(f"Meal plan {code} not found.")
        return plan

    async def _rates(
        self,
        quote: Quote,
        accommodation_id: uuid.UUID,
        nights: list[date],
        group: Group,
    ) -> dict[
        tuple[uuid.UUID, str, str], dict[date, dict[int, AccommodationRate]]
    ]:
        keys = group.residences
        ids = await residence_ids(self.db, keys)
        by_id = {value: name for name, value in ids.items()}
        stmt = (
            select(AccommodationRate, MealPlan.code)
            .join(MealPlan, MealPlan.id == AccommodationRate.meal_plan_id)
            .join(RoomType, RoomType.id == AccommodationRate.room_type_id)
            .where(
                RoomType.accommodation_id == accommodation_id,
                RoomType.is_active.is_(True),
                AccommodationRate.residence_category_id.in_(ids.values()),
                AccommodationRate.is_active.is_(True),
                AccommodationRate.effective_from <= nights[-1],
                AccommodationRate.effective_to >= nights[0],
            )
        )
        rows = list((await self.db.execute(stmt)).all())

        presentation = quote.presentation_currency.upper()
        index: dict[
            tuple[uuid.UUID, str, str], dict[date, dict[int, AccommodationRate]]
        ] = {}
        for rate, code in rows:
            residence = by_id.get(rate.residence_category_id)
            if residence is None:
                continue
            key = (rate.room_type_id, code.upper(), residence)
            per_night = index.setdefault(key, {})
            for night in nights:
                if not (rate.effective_from <= night <= rate.effective_to):
                    continue
                slot = per_night.setdefault(night, {})
                current = slot.get(rate.occupancy)
                if current is None or _supersedes(rate, current, presentation):
                    slot[rate.occupancy] = rate
        return index

    async def _per_cohort(
        self,
        quote: Quote,
        *,
        accommodation: list[CostLine],
        direct_lines: list[CostLine],
        shared: dict[str, Decimal],
        capacity_of: uuid.UUID,
        group: Group,
        nights: list[date],
        contingency_pct: Decimal,
        profit_pct: Decimal,
        agent_cover_fee: Decimal,
        rounding: Callable[[str], Decimal],
    ) -> GroupPrice | None:
        room_type = await self.db.get(RoomType, capacity_of)
        if room_type is None:
            return None
        presentation = quote.presentation_currency.upper()

        lines: list[CostLine] = list(accommodation)
        lines.extend(direct_lines)
        for label, amount in shared.items():
            if (
                label in {"accommodation", "park_fees", "activities", "transport"}
                or amount == 0
            ):
                continue
            lines.append(
                CostLine(
                    label=label,
                    amount=amount,
                    currency=presentation,
                    basis="per_group",
                )
            )

        convert, rate_used = await self._converter(
            {line.currency for line in lines}
            | {cohort.currency for cohort in group.cohorts}
            | {presentation},
            on_date=nights[0],
        )
        return price_group(
            lines=lines,
            group=group,
            capacity=room_type.max_occupancy,
            contingency_pct=contingency_pct,
            profit_pct=profit_pct,
            agent_cover_fee=agent_cover_fee,
            rounding_step=rounding,
            group_currency=presentation,
            convert=convert,
            rate_used=rate_used,
        )

    async def _converter(
        self, currencies: set[str], *, on_date: date
    ) -> tuple[
        Callable[[Decimal, str, str], Decimal], Callable[[str, str], Decimal]
    ]:
        rates: dict[tuple[str, str], Decimal] = {}
        for base in currencies:
            for quote_ccy in currencies:
                if base == quote_ccy:
                    rates[(base, quote_ccy)] = Decimal(1)
                    continue
                try:
                    rates[(base, quote_ccy)] = await self.fx.effective_rate(
                        base, quote_ccy, on_date
                    )
                except (AppError, NotFoundError):
                    continue

        def rate_for(base: str, quote_ccy: str) -> Decimal:
            try:
                return rates[(base.upper(), quote_ccy.upper())]
            except KeyError:
                raise AppError(
                    f"No exchange rate on file for {base.upper()} to "
                    f"{quote_ccy.upper()} on {on_date}, so this option cannot "
                    "be priced per cohort."
                ) from None

        def convert(amount: Decimal, base: str, quote_ccy: str) -> Decimal:
            return amount * rate_for(base, quote_ccy)

        return convert, rate_for

    async def _park_fees(
        self,
        quote: Quote,
        accommodation: Accommodation,
        *,
        nights: list[date],
        group: Group,
    ) -> tuple[Decimal, list[str], list[CostLine], list[CostEntry]]:
        residences = await residence_ids(self.db, group.residences)
        by_id = {value: name for name, value in residences.items()}
        rows = list(
            (
                await self.db.execute(
                    select(ParkFee).where(
                        ParkFee.destination_id == accommodation.destination_id,
                        ParkFee.fee_type == PARK_ENTRY,
                        ParkFee.residence_category_id.in_(residences.values()),
                        ParkFee.is_active.is_(True),
                        ParkFee.effective_from <= nights[-1],
                        ParkFee.effective_to >= nights[0],
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return Decimal(0), [], [], []

        index: dict[tuple[str, date], ParkFee] = {}
        for fee in rows:
            residence = by_id.get(fee.residence_category_id)
            if residence is None:
                continue
            for night in nights:
                if not (fee.effective_from <= night <= fee.effective_to):
                    continue
                current = index.get((residence, night))
                if current is None or fee.effective_from > current.effective_from:
                    index[(residence, night)] = fee

        per_cohort: dict[tuple[str, str, str], Decimal] = {}
        per_currency: dict[str, Decimal] = {}
        uncovered: set[str] = set()
        charged: dict[tuple[uuid.UUID, str, str], list] = {}
        for cohort in group.cohorts:
            for night in nights:
                tonight = index.get((cohort.residence, night))
                if tonight is None:
                    uncovered.add(cohort.residence)
                    continue
                amount = {
                    "adult": tonight.adult,
                    "child": tonight.child,
                    "infant": tonight.infant,
                }.get(cohort.traveller_type, tonight.adult)
                currency = tonight.currency.upper()
                charge = amount * cohort.count
                per_currency[currency] = per_currency.get(currency, Decimal(0)) + charge
                slot = (cohort.residence, cohort.traveller_type, currency)
                per_cohort[slot] = per_cohort.get(slot, Decimal(0)) + charge
                line = (tonight.id, cohort.residence, cohort.traveller_type)
                if line in charged:
                    charged[line][0] += cohort.count
                else:
                    charged[line] = [cohort.count, amount, tonight]

        lines = [
            CostLine(
                label="park_fees",
                amount=charge,
                currency=currency,
                basis="per_group",
                residence=residence,
                traveller_type=traveller_type,
            )
            for (residence, traveller_type, currency), charge in per_cohort.items()
        ]

        warnings: list[str] = []
        if uncovered:
            warnings.append(
                f"{accommodation.name}: this destination charges park fees but "
                f"none is on file for {', '.join(sorted(uncovered))} across the "
                f"whole stay, so those travellers are quoted without them. Load "
                f"the missing schedule before issuing."
            )
        entries = [
            CostEntry(
                label=(
                    f"Park entry, {accommodation.name}'s destination "
                    f"({residence} {traveller_type})"
                ),
                component="park_fees",
                basis="per_person_per_day",
                unit_amount=amount,
                quantity=person_days,
                currency=fee.currency.upper(),
                extended=amount * person_days,
                source=(
                    f"park_fees {fee.id} · {fee.fee_type} from {fee.effective_from}"
                ),
                residence=residence,
                traveller_type=traveller_type,
            )
            for (_, residence, traveller_type), (
                person_days,
                amount,
                fee,
            ) in charged.items()
        ]
        return (
            await self._to_presentation(quote, per_currency),
            warnings,
            lines,
            entries,
        )


    async def _activities(self, quote: Quote, *, group: Group) -> ActivityCosting:
        selected: dict[uuid.UUID, int | None] = {}
        for leg in quote.legs:
            for row in leg.activities:
                selected.setdefault(row.activity_id, row.day)
        if not selected:
            return ActivityCosting()

        included = list(
            (
                await self.db.execute(
                    select(Activity).where(
                        Activity.id.in_(selected),
                        Activity.is_mandatory.is_(True),
                        Activity.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not included:
            return ActivityCosting()

        residences = await residence_ids(self.db, group.residences)
        by_id = {value: name for name, value in residences.items()}
        days = {
            one.id: quote.arrival_date
            + timedelta(days=max(1, selected.get(one.id) or 1) - 1)
            for one in included
        }
        rows = list(
            (
                await self.db.execute(
                    select(ActivityRate).where(
                        ActivityRate.activity_id.in_([one.id for one in included]),
                        ActivityRate.residence_category_id.in_(residences.values()),
                        ActivityRate.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        index: dict[tuple[uuid.UUID, str], ActivityRate] = {}
        for rate in rows:
            residence = by_id.get(rate.residence_category_id)
            if residence is None:
                continue
            on = days.get(rate.activity_id)
            if on is None or not (rate.effective_from <= on <= rate.effective_to):
                continue
            key = (rate.activity_id, residence)
            current = index.get(key)
            if current is None or rate.effective_from > current.effective_from:
                index[key] = rate

        costing = ActivityCosting()
        per_currency: dict[str, Decimal] = {}
        uncovered: dict[str, set[str]] = {}
        assumed: set[str] = set()
        for activity in sorted(included, key=lambda one: one.name):
            costing.names.append(activity.name)
            costing.scheduled.append(
                Excursion(name=activity.name, day=selected.get(activity.id))
            )
            for cohort in group.cohorts:
                fare = index.get((activity.id, cohort.residence))
                if fare is None:
                    uncovered.setdefault(activity.name, set()).add(cohort.residence)
                    continue
                amount = {
                    "adult": fare.adult_price,
                    CHILD: fare.child_price,
                }.get(cohort.traveller_type)
                if amount is None:
                    amount = fare.adult_price
                    assumed.add(cohort.traveller_type)
                currency = fare.currency.upper()
                charge = amount * cohort.count
                if charge == 0:
                    continue
                per_currency[currency] = (
                    per_currency.get(currency, Decimal(0)) + charge
                )
                costing.lines.append(
                    CostLine(
                        label="activities",
                        amount=charge,
                        currency=currency,
                        basis="per_group",
                        residence=cohort.residence,
                        traveller_type=cohort.traveller_type,
                    )
                )
                costing.entries.append(
                    CostEntry(
                        label=(
                            f"{activity.name} — included "
                            f"({cohort.residence} {cohort.traveller_type})"
                        ),
                        component="activities",
                        basis="per_person",
                        unit_amount=amount,
                        quantity=cohort.count,
                        currency=currency,
                        extended=charge,
                        source=(
                            f"activity_rates {fare.id} · {activity.name} from "
                            f"{fare.effective_from}"
                        ),
                        residence=cohort.residence,
                        traveller_type=cohort.traveller_type,
                    )
                )

        for name, missing in sorted(uncovered.items()):
            costing.warnings.append(
                f"{name} is included in this quote but no rate is on file for "
                f"{', '.join(sorted(missing))} on the day it falls, so those "
                f"travellers are quoted without it. Load the rate before "
                f"issuing."
            )
        if assumed:
            costing.warnings.append(
                f"included activities are charged at the adult fare for "
                f"{', '.join(sorted(assumed))} travellers, because the rates "
                f"state an adult and a child price and nothing else"
            )
        costing.total = await self._to_presentation(quote, per_currency)
        return costing


    @staticmethod
    def _segment_label(segment: QuoteTransportSegment) -> str:
        parts = [
            "Transfer" if segment.kind == transport_rules.TRANSFER else "Line haul",
            segment.mode.upper(),
        ]
        if segment.travel_class:
            parts.append(segment.travel_class.title())
        label = " · ".join(parts)
        return f"{segment.description} ({label})" if segment.description else label

    async def _transport(self, quote: Quote, *, group: Group) -> TransportCosting:
        out = TransportCosting()
        segments = sorted(quote.transport_segments, key=lambda s: s.sequence)
        if not segments:
            return out

        per_currency: dict[str, Decimal] = {}
        optional_currency: dict[str, Decimal] = {}
        for segment in segments:
            label = self._segment_label(segment)
            if segment.mode in transport_rules.NAMED_ONLY_MODES:
                out.named.append(segment.description or label)
                continue
            if (
                segment.mode not in transport_rules.PRICED_MODES
                or segment.kind not in transport_rules.KINDS
            ):
                out.unpriced.append(label)
                continue
            on = segment.travel_date or quote.arrival_date
            if segment.vehicle_id is not None:
                await self._drive(
                    quote,
                    segment,
                    label=label,
                    on=on,
                    group=group,
                    into=out,
                    per_currency=per_currency,
                    optional_currency=optional_currency,
                )
                continue

            if not (quote.arrival_date <= on <= quote.departure_date):
                out.warnings.append(
                    f"{label} travels on {on}, which is outside the quote's "
                    f"{quote.arrival_date} to {quote.departure_date} window, so "
                    f"it is priced at that date's tariff. Check the date."
                )
            tariff = await self._tariff_for(segment, on=on)
            if tariff is None:
                out.unpriced.append(label)
                out.warnings.append(
                    f"{label}: no tariff on file for this destination and "
                    f"vehicle on {on}, so the movement carries no price. Load "
                    f"the fare before issuing — a zero here reads on the "
                    f"document as a leg the client is not being charged for."
                )
                continue

            amount, currency, basis, tariff_label, source = tariff
            if (
                segment.kind == transport_rules.TRANSFER
                and segment.description
                and tariff_label
                and tariff_label.strip().casefold()
                != segment.description.strip().casefold()
            ):
                out.warnings.append(
                    f"{label} is priced off the {tariff_label!r} tariff, which "
                    f"is not the route named. Load a rate for this leg, or "
                    f"rename it to the tariff it is actually charged at."
                )
            cost = amount * multiplier(
                basis, pax=group.pax, nights=0, days=0, rooms=0, units=segment.units
            )
            charge = TransportCharge(
                sequence=segment.sequence,
                kind=segment.kind,
                mode=segment.mode,
                label=segment.description or tariff_label or label,
                basis=basis,
                units=segment.units,
                unit_amount=amount,
                currency=currency,
                cost=cost,
                is_optional=segment.is_optional,
                is_vvip=segment.is_vvip,
                source=source,
            )
            if segment.is_optional:
                out.optional.append(charge)
                optional_currency[currency] = (
                    optional_currency.get(currency, Decimal(0)) + cost
                )
                continue
            out.charges.append(charge)
            per_currency[currency] = per_currency.get(currency, Decimal(0)) + cost
            out.lines.append(
                CostLine(
                    label="transport",
                    amount=cost,
                    currency=currency,
                    basis="per_group",
                )
            )

        out.total = await self._to_presentation(quote, per_currency)
        out.optional_total = await self._to_presentation(quote, optional_currency)
        out.entries = [
            CostEntry(
                label=(
                    f"{charge.label} (optional)" if charge.is_optional
                    else charge.label
                ),
                component=(
                    "transport_optional" if charge.is_optional else "transport"
                ),
                basis=charge.basis,
                unit_amount=charge.unit_amount,
                quantity=(
                    charge.units
                    if charge.sequence in out.roads
                    else multiplier(
                        charge.basis,
                        pax=group.pax,
                        nights=0,
                        days=0,
                        rooms=0,
                        units=charge.units,
                    )
                ),
                currency=charge.currency,
                extended=charge.cost,
                source=charge.source,
            )
            for charge in out.charges + out.optional
        ]
        return out

    async def _drive(
        self,
        quote: Quote,
        segment: QuoteTransportSegment,
        *,
        label: str,
        on: date,
        group: Group,
        into: TransportCosting,
        per_currency: dict[str, Decimal],
        optional_currency: dict[str, Decimal],
    ) -> None:
        vehicle = await self.db.get(Vehicle, segment.vehicle_id)
        if vehicle is None:
            raise NotFoundError(
                "A transport segment references a vehicle that no longer exists."
            )

        if segment.origin_id is None or segment.destination_id is None:
            gap = routing.check_endpoints(
                label=label,
                has_origin=segment.origin_id is not None,
                has_destination=segment.destination_id is not None,
                sequence=segment.sequence,
            )
            if gap is not None:
                into.problems.append(gap)
            into.unpriced.append(label)
            return

        road = await RouteService(self.db).find(
            origin_id=segment.origin_id,
            destination_id=segment.destination_id,
            on=on,
        )
        if road is None:
            into.problems.append(
                routing.missing_route(label=label, sequence=segment.sequence, on=on)
            )
            into.unpriced.append(label)
            return

        fault = routing.check_vehicle(
            label=label,
            road=road,
            offered=vehicle.vehicle_type,
            sequence=segment.sequence,
        )
        if fault is not None:
            into.problems.append(fault)

        try:
            fuel = await FuelPriceService(self.db).select_price(
                fuel_type=vehicle.fuel_type, on_date=on
            )
        except (AppError, NotFoundError):
            into.problems.append(
                routing.missing_fuel_price(
                    label=label,
                    fuel_type=vehicle.fuel_type,
                    sequence=segment.sequence,
                )
            )
            into.unpriced.append(label)
            return

        vehicles = max(1, segment.units)
        calc = compute_transport_cost(
            distance_km=road.distance_km,
            consumption_kmpl=vehicle.fuel_consumption_kmpl,
            fuel_price_per_litre=fuel.price_per_litre,
            days=routing.DAYS_PER_MOVEMENT,
            driver_cost_per_day=vehicle.driver_cost_per_day,
            daily_operating_cost=vehicle.daily_operating_cost,
        )
        fuel_currency = fuel.currency.upper()
        crew_currency = vehicle.currency.upper()
        fuel_cost = calc["fuel_cost"] * vehicles
        crew_cost = (calc["driver_total"] + calc["operating_total"]) * vehicles

        into.roads[segment.sequence] = road
        bucket = optional_currency if segment.is_optional else per_currency
        target = into.optional if segment.is_optional else into.charges
        for currency, amount, what, unit, basis in (
            (
                fuel_currency,
                fuel_cost,
                f"{label} — fuel, {routing.plain(road.distance_km)} km at "
                f"{routing.plain(vehicle.fuel_consumption_kmpl)} km/L",
                fuel.price_per_litre,
                "per_vehicle",
            ),
            (
                crew_currency,
                crew_cost,
                f"{label} — driver and running, {routing.plain(road.hours)} h",
                vehicle.driver_cost_per_day + vehicle.daily_operating_cost,
                "per_vehicle",
            ),
        ):
            if amount == 0:
                continue
            bucket[currency] = bucket.get(currency, Decimal(0)) + amount
            target.append(
                TransportCharge(
                    sequence=segment.sequence,
                    kind=segment.kind,
                    mode=segment.mode,
                    label=what,
                    basis=basis,
                    units=vehicles,
                    unit_amount=unit,
                    currency=currency,
                    cost=amount,
                    is_optional=segment.is_optional,
                    is_vvip=segment.is_vvip,
                    source=(
                        f"{road.source} · vehicles {vehicle.id} "
                        f"({vehicle.vehicle_type})"
                        + (
                            f" · fuel_prices {fuel.id}"
                            if basis == "per_vehicle" and currency == fuel_currency
                            else ""
                        )
                    ),
                )
            )
            if not segment.is_optional:
                into.lines.append(
                    CostLine(
                        label="transport",
                        amount=amount,
                        currency=currency,
                        basis="per_group",
                    )
                )

    async def _tariff_for(
        self, segment: QuoteTransportSegment, *, on: date
    ) -> tuple[Decimal, str, str, str, str] | None:
        if segment.destination_id is None:
            return None

        if segment.kind == transport_rules.TRANSFER:
            rows = list(
                (
                    await self.db.execute(
                        select(TransferRate).where(
                            TransferRate.destination_id == segment.destination_id,
                            TransferRate.vehicle_type == (segment.vehicle_type or ""),
                            TransferRate.is_active.is_(True),
                            TransferRate.effective_from <= on,
                        )
                    )
                )
                .scalars()
                .all()
            )
            live = [r for r in rows if r.effective_to is None or r.effective_to >= on]
            if not live:
                return None
            wanted = (segment.description or "").strip().casefold()
            best = max(
                live,
                key=lambda r: (
                    2 if wanted and r.route_label.strip().casefold() == wanted else
                    1 if not r.route_label.strip() else 0,
                    r.effective_from,
                ),
            )
            return (
                to_vat_inclusive(
                    best.price_per_leg,
                    vat_inclusive=best.vat_inclusive,
                    vat_pct=best.vat_pct,
                ),
                best.currency.upper(),
                transport_rules.line_basis("per_leg"),
                best.route_label,
                f"transfer_rates {best.id} · {best.vehicle_type} from "
                f"{best.effective_from}",
            )

        fares = list(
            (
                await self.db.execute(
                    select(DestinationTransportMode).where(
                        DestinationTransportMode.destination_id
                        == segment.destination_id,
                        DestinationTransportMode.mode == segment.mode,
                        DestinationTransportMode.travel_class
                        == (segment.travel_class or ""),
                        DestinationTransportMode.is_active.is_(True),
                        DestinationTransportMode.effective_from <= on,
                    )
                )
            )
            .scalars()
            .all()
        )
        current = [f for f in fares if f.effective_to is None or f.effective_to >= on]
        if not current:
            return None
        fare = max(current, key=lambda f: f.effective_from)
        return (
            to_vat_inclusive(
                fare.price, vat_inclusive=fare.vat_inclusive, vat_pct=fare.vat_pct
            ),
            fare.currency.upper(),
            transport_rules.line_basis(fare.cost_basis),
            fare.label or "",
            f"destination_transport_modes {fare.id} · {fare.mode}"
            + (f" {fare.travel_class}" if fare.travel_class else "")
            + f" from {fare.effective_from}",
        )

    async def _supplements(
        self,
        quote: Quote,
        accommodation_id: uuid.UUID,
        *,
        room_type_id: uuid.UUID,
        meal_plan_id: uuid.UUID,
        nights: list[date],
        pax: int,
        rooms: int,
    ) -> list[SupplementCharge]:
        stmt = select(AccommodationSupplement).where(
            AccommodationSupplement.accommodation_id == accommodation_id,
            AccommodationSupplement.is_active.is_(True),
            AccommodationSupplement.is_mandatory.is_(True),
            AccommodationSupplement.effective_from <= nights[-1],
            AccommodationSupplement.effective_to >= nights[0],
        )
        out: list[SupplementCharge] = []
        for row in (await self.db.execute(stmt)).scalars().all():
            if row.room_type_id is not None and row.room_type_id != room_type_id:
                continue
            if row.meal_plan_id is not None and row.meal_plan_id != meal_plan_id:
                continue
            if (
                row.residence_category_id is not None
                and row.residence_category_id != quote.residence_category_id
            ):
                continue
            affected = sum(
                1 for night in nights if row.effective_from <= night <= row.effective_to
            )
            cost = supplement_cost(
                amount=row.amount,
                basis=row.basis,
                pax=pax,
                rooms=rooms,
                nights=affected,
            )
            if cost == 0:
                continue
            out.append(
                SupplementCharge(
                    label=row.label,
                    kind=row.kind,
                    basis=row.basis,
                    amount=row.amount,
                    currency=row.currency.upper(),
                    nights=affected,
                    units=multiplier(
                        row.basis,
                        pax=pax,
                        nights=affected,
                        days=affected,
                        rooms=rooms,
                    ),
                    source=(
                        f"accommodation_supplements {row.id} · {row.kind} "
                        f"from {row.effective_from}"
                    ),
                    cost=await self.fx.convert(
                        cost,
                        row.currency.upper(),
                        quote.presentation_currency.upper(),
                        nights[0],
                    ),
                )
            )
        return out

    async def _to_presentation(
        self, quote: Quote, amounts: dict[str, Decimal]
    ) -> Decimal:
        target = quote.presentation_currency.upper()
        total = Decimal(0)
        for currency, amount in amounts.items():
            total += await self.fx.convert(amount, currency, target, quote.arrival_date)
        return total

    async def _load(self, quote_id: uuid.UUID) -> Quote:
        quote = (
            await self.db.execute(select(Quote).where(Quote.id == quote_id))
        ).scalar_one_or_none()
        if quote is None:
            raise NotFoundError("Quote not found.")
        return quote
