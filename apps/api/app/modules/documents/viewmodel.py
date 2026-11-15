from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import read_bytes
from app.modules.accommodations.models import Accommodation
from app.modules.activities.models import Activity, ActivityPriceTier
from app.modules.activities.service import ActivityRateService
from app.modules.clients.models import Client
from app.modules.destinations.models import Destination
from app.modules.documents.config import DocumentConfig
from app.modules.media.models import DestinationImage, PropertyImage
from app.modules.narratives.service import property_copy
from app.modules.quotes.models import Quote, QuoteVersion

MEAL_PLAN_PHRASES: dict[str, str] = {
    "AI": "All-inclusive meals",
    "FB": "Full-board meals",
    "HB": "Half-board meals",
    "BB": "Bed & breakfast",
    "RO": "Room only",
}

SELF_CATERING_PLANS = frozenset({"BB", "RO"})


def money(amount: Decimal | str | None, currency: str) -> str | None:
    if amount is None:
        return None
    value = Decimal(amount)
    if value == value.to_integral_value():
        return f"{currency} {int(value):,}"
    return f"{currency} {value:,.2f}"


@dataclass(frozen=True)
class Fact:

    label: str
    value: str


@dataclass(frozen=True)
class Image:
    url: str
    alt: str


@dataclass(frozen=True)
class ItineraryLeg:

    step: str
    destination: str
    property_name: str
    nights: str
    room: str
    board: str


@dataclass(frozen=True)
class DayView:

    label: str
    on: str
    place: str
    property_name: str
    move: str
    events: list[str]
    board: str
    is_arrival: bool = False
    is_departure: bool = False


@dataclass(frozen=True)
class CohortPriceView:

    label: str
    headcount: str
    per_person: str
    total: str


@dataclass
class OptionView:

    number: str
    name: str
    tagline: str
    blurb: str | None
    is_recommended: bool
    is_comparable: bool
    facts: list[Fact]
    included: list[str]
    per_person: str | None
    group_total: str
    hero: Image | None
    gallery: list[Image] = field(default_factory=list)
    comparability_note: str | None = None
    itinerary: list[ItineraryLeg] = field(default_factory=list)
    route: str = ""
    cohorts: list[CohortPriceView] = field(default_factory=list)
    days: list[DayView] = field(default_factory=list)


@dataclass(frozen=True)
class ComparisonRow:
    name: str
    route: str
    rooming: str
    meal_plan: str
    transport: str
    per_person: str | None
    group_total: str
    is_recommended: bool


@dataclass(frozen=True)
class RejectedView:
    name: str
    reason: str


@dataclass(frozen=True)
class TransferLeg:
    route: str
    note: str


@dataclass
class TransportView:
    heading: str
    summary: str
    route_label: str
    legs: list[TransferLeg]
    capacity: str
    hero: Image | None = None
    label: str = ""
    named: list[str] = field(default_factory=list)
    add_on: str | None = None


@dataclass
class ExperienceView:

    name: str
    description: str | None
    includes: list[str]
    per_person: str | None
    is_optional: bool
    tiers: list[Fact] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)


@dataclass
class QuotationView:
    config: DocumentConfig
    quote_number: str
    title: str
    subtitle: str
    destination_label: str
    client_name: str
    currency: str
    cover: Image | None
    cover_facts: list[Fact]
    intro_heading: str
    intro_paragraphs: list[str]
    glance: list[Fact]
    options: list[OptionView]
    comparison: list[ComparisonRow]
    rejected: list[RejectedView]
    transport: TransportView | None
    experiences: list[ExperienceView]
    exclusions: list[str]
    programme: list[DayView]
    programme_option: str
    valid_until: date | None
    issued_on: date


class QuotationViewBuilder:

    def __init__(self, db: AsyncSession, *, inline_assets: bool = True):
        self.db = db
        self.inline_assets = inline_assets

    async def build(
        self, quote: Quote, version: QuoteVersion, config: DocumentConfig
    ) -> QuotationView:
        snapshot = version.snapshot or {}
        currency = version.currency.upper()
        pax = int(snapshot.get("pax_count") or quote.pax_count or 0)
        nights = self._nights(quote)
        client = await self.db.get(Client, quote.client_id)
        destination = await self._destination(quote)
        transport = await self._transport(
            snapshot.get("transport") or {}, pax, destination, currency
        )

        raw_options = sorted(
            snapshot.get("options", []), key=lambda o: o.get("sort_order") or 0
        )
        options: list[OptionView] = []
        for index, raw in enumerate(raw_options, start=1):
            options.append(
                await self._option(
                    raw, index, currency, pax, transport is not None, config
                )
            )

        programme, programme_option = self._programme(options)

        return QuotationView(
            config=config,
            quote_number=quote.quote_number,
            title=quote.document_title or self._default_title(destination),
            subtitle=(
                quote.document_subtitle
                or f"A curated experience by {config.company_name}"
            ),
            destination_label=self._destination_label(destination),
            client_name=client.name if client else "",
            currency=currency,
            cover=await self._cover(destination),
            cover_facts=self._cover_facts(
                pax, destination, client, options, transport
            ),
            intro_heading=self._intro_heading(destination),
            intro_paragraphs=self._intro(config, pax, len(options), destination),
            glance=self._glance(pax, nights, destination, options, transport, config),
            options=options,
            comparison=self._comparison(options, transport),
            rejected=[
                RejectedView(name=r["name"], reason=r["reason"])
                for r in snapshot.get("rejected", [])
            ],
            transport=transport,
            experiences=await self._experiences(quote, currency),
            exclusions=self._exclusions(config, transport),
            programme=programme,
            programme_option=programme_option,
            valid_until=quote.valid_until,
            issued_on=version.created_at.date(),
        )


    async def _option(
        self,
        raw: dict,
        index: int,
        currency: str,
        pax: int,
        has_transport: bool,
        config: DocumentConfig,
    ) -> OptionView:
        plan_code = str(raw.get("meal_plan_code") or "").upper()
        plan_name = str(raw.get("meal_plan_name") or plan_code)
        room = str(raw.get("room_type_name") or "")
        rooms = raw.get("rooms_required")
        nights = raw.get("nights")
        accommodation_id = raw.get("accommodation_id")

        facts = [
            Fact("Accommodation", room),
            Fact("Meal plan", plan_name),
            Fact("Group size", f"{pax} participants"),
        ]
        if rooms:
            count = int(rooms)
            facts.append(
                Fact("Rooms required", f"{count} room" + ("s" if count > 1 else ""))
            )
        if nights:
            facts.append(Fact("Nights", f"{nights} nights"))
        if has_transport:
            facts.append(Fact("Transport", "Complete group transfers"))

        included = ["Accommodation"]
        if plan_code in SELF_CATERING_PLANS:
            included.append("Group meal arrangement")
        else:
            included.append(MEAL_PLAN_PHRASES.get(plan_code, plan_name))
        if has_transport:
            included.append("Complete group transfers")
        included.extend(
            str(name) for name in (raw.get("activities") or []) if str(name)
        )
        included.append(f"{config.company_name} coordination")

        legs = sorted(
            raw.get("legs") or [], key=lambda leg: leg.get("sequence") or 0
        )
        itinerary = [
            ItineraryLeg(
                step=f"{index:02d}",
                destination=str(leg.get("destination_name") or ""),
                property_name=str(leg.get("accommodation_name") or ""),
                nights=self._nights_phrase(leg.get("nights")),
                room=str(leg.get("room_type_name") or ""),
                board=str(leg.get("meal_plan_name") or leg.get("meal_plan_code") or ""),
            )
            for index, leg in enumerate(legs, start=1)
        ]
        route = " → ".join(
            one.destination or one.property_name for one in itinerary
        )

        cohorts = [
            CohortPriceView(
                label=self._cohort_label(row),
                headcount=self._people_phrase(row.get("headcount")),
                per_person=money(row.get("per_person"), str(row.get("currency") or ""))
                or "",
                total=money(row.get("total"), str(row.get("currency") or "")) or "",
            )
            for row in raw.get("cohorts") or []
        ]
        if len(cohorts) < 2:
            cohorts = []

        days = self._days(raw.get("days") or [])

        hero, gallery = await self._property_images(accommodation_id)
        blurb = raw.get("blurb") or await self._blurb(accommodation_id)
        comparable = bool(raw.get("is_comparable", True))
        fallback_from = raw.get("meal_plan_fallback_from")
        note = None
        if not comparable and plan_code == "AI" and fallback_from:
            requested_name = MEAL_PLAN_PHRASES.get(
                str(fallback_from).upper(), str(fallback_from)
            ).lower()
            note = (
                f"You asked about {requested_name}; this property only offers "
                f"all-inclusive, so that is what is priced here. It usually "
                f"costs more than {requested_name} elsewhere, because it "
                f"includes drinks and extras the other options do not."
            )
        elif not comparable:
            note = (
                f"This option is structured differently from the others — "
                f"{plan_name.lower()} rather than a like-for-like package — so it "
                f"is not presented as directly equivalent."
            )

        return OptionView(
            number=f"{index:02d}",
            name=str(raw.get("accommodation_name") or ""),
            tagline=" · ".join(part for part in (plan_name, room) if part),
            blurb=blurb,
            is_recommended=bool(raw.get("is_recommended")),
            is_comparable=comparable,
            facts=facts,
            included=included,
            per_person=money(raw.get("per_person"), currency),
            group_total=money(
                raw.get("client_total") or raw.get("group_total"), currency
            )
            or "",
            hero=hero,
            gallery=gallery,
            comparability_note=note,
            itinerary=itinerary,
            days=days,
            route=route,
            cohorts=cohorts,
        )

    @staticmethod
    def _programme(options: list[OptionView]) -> tuple[list[DayView], str]:
        if not options:
            return [], ""
        chosen = next((one for one in options if one.is_recommended), options[0])
        days = chosen.days
        worth_printing = any(day.events for day in days) or len(chosen.itinerary) > 1
        if not days or not worth_printing:
            return [], ""
        return days, chosen.name

    def _days(self, frozen: list[dict]) -> list[DayView]:
        out: list[DayView] = []
        for row in frozen:
            events = [
                self._movement_phrase(one) for one in (row.get("movements") or []) if one
            ]
            events.extend(str(one) for one in (row.get("excursions") or []) if one)
            board = str(row.get("board") or "")
            phrase = (
                "Checkout"
                if row.get("is_departure")
                else MEAL_PLAN_PHRASES.get(board, board)
            )
            place = str(row.get("destination") or "")
            property_name = str(row.get("property_name") or "")
            leaving = str(row.get("moves_from") or "")
            out.append(
                DayView(
                    label=f"Day {int(row.get('number') or 0):02d}",
                    on=self._day_date(str(row.get("date") or "")),
                    place=place,
                    property_name=property_name,
                    move=(
                        f"{leaving} \u2192 {property_name}"
                        if leaving and property_name
                        else ""
                    ),
                    events=events,
                    board=phrase,
                    is_arrival=bool(row.get("is_arrival")),
                    is_departure=bool(row.get("is_departure")),
                )
            )
        return out

    @classmethod
    def _movement_phrase(cls, movement: Any) -> str:
        if not isinstance(movement, dict):
            return str(movement)
        label = str(movement.get("label") or "")
        phrase = cls._drive_phrase(movement.get("minutes"))
        return f"{label} — {phrase}" if label and phrase else label

    @staticmethod
    def _drive_phrase(minutes: Any) -> str:
        try:
            total = int(minutes)
        except (TypeError, ValueError):
            return ""
        if total <= 0:
            return ""
        if total < 90:
            return f"about {total} min"
        hours, rest = divmod(total, 60)
        return f"about {hours} h" if not rest else f"about {hours} h {rest:02d}"

    @staticmethod
    def _day_date(iso: str) -> str:
        if not iso:
            return ""
        try:
            when = date.fromisoformat(iso)
        except ValueError:
            return iso
        return when.strftime("%a %d %b")

    @staticmethod
    def _nights_phrase(nights: Any) -> str:
        count = int(nights or 0)
        return "" if not count else f"{count} night" + ("s" if count > 1 else "")

    @staticmethod
    def _people_phrase(headcount: Any) -> str:
        count = int(headcount or 0)
        return "" if not count else f"{count} traveller" + ("s" if count > 1 else "")

    @staticmethod
    def _cohort_label(row: dict) -> str:
        residence = str(row.get("residence_label") or row.get("residence") or "")
        kind = str(row.get("traveller_type") or "").strip()
        if kind and kind != "adult":
            return f"{residence} · {kind}ren" if kind == "child" else (
                f"{residence} · {kind}s"
            )
        return residence

    def _comparison(
        self, options: list[OptionView], transport: TransportView | None
    ) -> list[ComparisonRow]:
        rows = [
            ComparisonRow(
                name=option.name,
                route=option.route,
                rooming=next(
                    (f.value for f in option.facts if f.label == "Accommodation"), ""
                ),
                meal_plan=next(
                    (f.value for f in option.facts if f.label == "Meal plan"), ""
                ),
                transport=(
                    transport.label or transport.heading
                    if transport is not None
                    else "Not included"
                ),
                per_person=option.per_person,
                group_total=option.group_total,
                is_recommended=option.is_recommended,
            )
            for option in options
        ]
        return sorted(rows, key=lambda r: _numeric(r.group_total))


    @staticmethod
    def _default_title(destination: Destination | None) -> str:
        if destination is None:
            return "Travel Proposal"
        return f"{destination.name} Experience"

    @staticmethod
    def _destination_label(destination: Destination | None) -> str:
        if destination is None:
            return ""
        parts = [destination.region, destination.name]
        return " · ".join(p for p in parts if p)

    @staticmethod
    def _intro_heading(destination: Destination | None) -> str:
        where = destination.name if destination else "Your Trip"
        return f"A {where} Experience, Curated for Your Team"

    @staticmethod
    def _intro(
        config: DocumentConfig,
        pax: int,
        option_count: int,
        destination: Destination | None,
    ) -> list[str]:
        where = destination.name if destination else "your chosen destination"
        return [
            f"{config.company_name} is delighted to present this curated proposal "
            f"for a group of {pax} participants.",
            f"We have sourced {option_count} accommodation options across different "
            f"levels of comfort and experience, allowing your organisation to select "
            f"the one that best aligns with its preferred balance of hospitality, "
            f"convenience and budget.",
            f"From coordinated group transportation to accommodation and meals, our "
            f"role is to make the journey seamless from departure to arrival, "
            f"allowing your team to focus on connection, relaxation and enjoying "
            f"{where}.",
        ]

    def _cover_facts(
        self,
        pax: int,
        destination: Destination | None,
        client: Client | None,
        options: list[OptionView],
        transport: TransportView | None,
    ) -> list[Fact]:
        facts = [Fact("Group", f"{pax} participants")]
        if destination is not None:
            facts.append(Fact("Destination", destination.name))
        if client is not None:
            facts.append(Fact("Client", client.name))
        if options:
            facts.append(Fact("Options", f"{len(options)} to choose from"))
        if transport is not None:
            facts.append(Fact("Transfers", transport.capacity))
        return facts

    def _glance(
        self,
        pax: int,
        nights: int,
        destination: Destination | None,
        options: list[OptionView],
        transport: TransportView | None,
        config: DocumentConfig,
    ) -> list[Fact]:
        facts = [Fact("Group size", f"{pax} participants")]
        if destination is not None:
            facts.append(Fact("Destination", self._destination_label(destination)))
        if transport is not None:
            facts.append(Fact("Transport", transport.heading))
        if nights:
            facts.append(Fact("Duration", f"{nights} nights"))
        if options:
            facts.append(Fact("Accommodation", f"{len(options)} curated options"))
        facts.append(Fact("Pricing", config.vat_note))
        return facts

    @staticmethod
    def _exclusions(
        config: DocumentConfig, transport: TransportView | None
    ) -> list[str]:
        out = list(config.exclusions)
        if transport is not None:
            for flight in transport.named:
                out.insert(
                    0,
                    f"Air tickets ({flight}) — Acacia does not ticket air "
                    f"travel, so these are booked directly by you",
                )
            if transport.add_on:
                out.append(
                    f"Optional transport upgrades, quoted separately at "
                    f"{transport.add_on}"
                )
        return out

    @staticmethod
    def _nights(quote: Quote) -> int:
        return max(0, (quote.departure_date - quote.arrival_date).days)


    async def _transport(
        self,
        journey: dict,
        pax: int,
        destination: Destination | None,
        currency: str,
    ) -> TransportView | None:
        movements = sorted(
            journey.get("movements") or [], key=lambda m: m.get("sequence") or 0
        )
        named = [str(one) for one in journey.get("named") or []]
        if not movements and not named:
            return None

        counted: dict[tuple[str, str], int] = {}
        for one in movements:
            key = (
                str(one.get("label") or "").strip() or self._movement_label(one),
                "Optional upgrade" if one.get("is_optional") else "Included",
            )
            counted[key] = counted.get(key, 0) + 1
        legs = [
            TransferLeg(
                route=route if count == 1 else f"{route} × {count}", note=note
            )
            for (route, note), count in counted.items()
        ]
        legs.extend(TransferLeg(route=one, note="Booked by you") for one in named)
        modes = sorted({str(one.get("mode") or "").upper() for one in movements})
        add_on = Decimal(str(journey.get("optional_price") or "0"))
        return TransportView(
            heading=" + ".join(modes) if modes else "Air",
            summary=(
                "To keep the group travelling together comfortably, transport is "
                "arranged as a complete door-to-door journey, and the same in "
                "reverse."
            ),
            route_label=" → ".join(dict.fromkeys(leg.route for leg in legs)),
            legs=legs,
            capacity=f"{pax} pax",
            hero=await self._cover(destination) if destination else None,
            label=self._journey_label(modes, named),
            named=named,
            add_on=money(add_on, currency) if add_on > 0 else None,
        )

    @staticmethod
    def _movement_label(movement: dict) -> str:
        kind = "Transfer" if movement.get("kind") == "transfer" else "Line haul"
        return f"{kind} · {str(movement.get('mode') or '').upper()}"

    @staticmethod
    def _journey_label(modes: list[str], named: list[str]) -> str:
        words = [mode.title() for mode in modes]
        if not words:
            return "Flights booked by you"
        joined = words[0] if len(words) == 1 else " and ".join(
            (", ".join(words[:-1]), words[-1])
        )
        return f"{joined} transfers" + (" · flights excluded" if named else "")


    async def _experiences(
        self, quote: Quote, currency: str
    ) -> list[ExperienceView]:
        activity_ids = [
            selection.activity_id
            for leg in quote.legs
            for selection in leg.activities
        ]
        if not activity_ids:
            return []
        activities = (
            (
                await self.db.execute(
                    select(Activity).where(
                        Activity.id.in_(activity_ids),
                        Activity.has_own_section.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        rates = ActivityRateService(self.db)
        out: list[ExperienceView] = []
        for activity in activities:
            per_person = None
            try:
                rate = await rates.select_rate(
                    activity_id=activity.id,
                    residence_category_id=quote.residence_category_id,
                    on_date=quote.arrival_date,
                )
                per_person = money(rate.adult_price, rate.currency.upper())
            except Exception:  # noqa: BLE001
                per_person = None
            tiers = (
                (
                    await self.db.execute(
                        select(ActivityPriceTier)
                        .where(
                            ActivityPriceTier.activity_id == activity.id,
                            ActivityPriceTier.residence_category_id
                            == quote.residence_category_id,
                            ActivityPriceTier.effective_from <= quote.arrival_date,
                        )
                        .order_by(ActivityPriceTier.sort_order)
                    )
                )
                .scalars()
                .all()
            )
            out.append(
                ExperienceView(
                    name=activity.name,
                    description=activity.description,
                    includes=[],
                    per_person=per_person,
                    is_optional=activity.is_optional,
                    tiers=[
                        Fact(tier.label, money(tier.price, tier.currency.upper()) or "")
                        for tier in tiers
                    ],
                    images=[],
                )
            )
        return out


    async def _cover(self, destination: Destination | None) -> Image | None:
        if destination is None:
            return None
        row = (
            await self.db.execute(
                select(DestinationImage)
                .where(DestinationImage.destination_id == destination.id)
                .order_by(
                    DestinationImage.is_cover.desc(), DestinationImage.sort_order
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return self._image(row, "destination-images", row.alt_text or destination.name)

    async def _property_images(
        self, accommodation_id: str | None
    ) -> tuple[Image | None, list[Image]]:
        if not accommodation_id:
            return None, []
        rows = (
            (
                await self.db.execute(
                    select(PropertyImage)
                    .where(
                        PropertyImage.accommodation_id == uuid.UUID(accommodation_id)
                    )
                    .order_by(
                        PropertyImage.is_hero.desc(), PropertyImage.sort_order
                    )
                )
            )
            .scalars()
            .all()
        )
        images = [
            image
            for image in (
                self._image(row, "property-images", row.alt_text or "") for row in rows
            )
            if image is not None
        ]
        if not images:
            return None, []
        return images[0], images[1:5]

    def _image(self, row: Any, kind: str, alt: str) -> Image | None:
        if not self.inline_assets:
            return Image(url=f"/api/v1/{kind}/{row.id}/file", alt=alt)
        try:
            payload = base64.b64encode(read_bytes(row.storage_path)).decode("ascii")
        except (OSError, ValueError):
            return None
        return Image(url=f"data:{row.content_type};base64,{payload}", alt=alt)

    async def _blurb(self, accommodation_id: str | None) -> str | None:
        if not accommodation_id:
            return None
        accommodation = await self.db.get(Accommodation, uuid.UUID(accommodation_id))
        if accommodation is None:
            return None
        return await property_copy(self.db, accommodation)

    async def _destination(self, quote: Quote) -> Destination | None:
        for leg in sorted(quote.legs, key=lambda leg: leg.sequence):
            found = await self.db.get(Destination, leg.destination_id)
            if found is not None:
                return found
        for option in sorted(quote.options, key=lambda o: o.sort_order):
            accommodation = await self.db.get(Accommodation, option.accommodation_id)
            if accommodation is not None:
                return await self.db.get(Destination, accommodation.destination_id)
        return None


def _numeric(formatted: str) -> Decimal:
    digits = "".join(c for c in formatted if c.isdigit() or c == ".")
    return Decimal(digits) if digits else Decimal(0)
