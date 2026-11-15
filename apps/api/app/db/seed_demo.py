from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.modules.accommodations.models import (
    Accommodation,
    AccommodationRate,
    AccommodationSupplement,
    MealPlan,
    RoomType,
)
from app.modules.activities.models import Activity, ActivityPriceTier, ActivityRate
from app.modules.destinations.models import Destination
from app.modules.park_fees.models import ParkFee
from app.modules.residence.models import ResidenceCategory
from app.modules.transport.models import DestinationTransportMode, TransferRate
from app.modules.vehicles.models import FuelPrice, Vehicle

SEASON_FROM = date(2026, 1, 1)
SEASON_TO = date(2035, 12, 31)
FESTIVE_FROM = date(2026, 12, 20)
FESTIVE_TO = date(2027, 1, 2)
FESTIVE_MIN_NIGHTS = 4
SUPPLEMENT_FROM = date(2026, 12, 24)
SUPPLEMENT_TO = date(2026, 12, 25)

DEMO_MARKER = "demo-sample"


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-").replace("&", "and").replace("--", "-")


async def _get_or_create(
    db: AsyncSession, model: Any, where: Any, **defaults: Any
) -> Any:
    existing = (await db.execute(select(model).where(where))).scalar_one_or_none()
    if existing is not None:
        return existing
    row = model(**defaults)
    db.add(row)
    await db.flush()
    return row


async def seed_demo(db: AsyncSession) -> dict[str, Any]:
    residence = {
        r.key: r for r in (await db.execute(select(ResidenceCategory))).scalars().all()
    }
    meal_plans = {m.code: m for m in (await db.execute(select(MealPlan))).scalars().all()}
    if not residence or not meal_plans:
        raise RuntimeError("Run `python -m app.db.seed` first — base reference data missing.")

    citizen = residence["citizen"]
    non_resident = residence["non_resident"]
    bb, hb, fb = meal_plans["BB"], meal_plans["HB"], meal_plans["FB"]

    diani = await _get_or_create(
        db,
        Destination,
        Destination.slug == "demo-diani",
        name="Diani (demo)",
        slug="demo-diani",
        type="beach",
        country="Kenya",
        region="Coast",
    )
    mara = await _get_or_create(
        db,
        Destination,
        Destination.slug == "demo-mara-reserve",
        name="Mara Reserve (demo)",
        slug="demo-mara-reserve",
        type="reserve",
        country="Kenya",
        region="Rift Valley",
    )

    properties: dict[str, Accommodation] = {}
    for name, category in (
        ("Coral Shoals Resort", "resort"),
        ("Mvule Beach Lodge", "lodge"),
        ("Upepo Guest House", "guesthouse"),
        ("Pendo Demo Villas", "villa"),
        ("Chui Festive Camp", "camp"),
    ):
        properties[name] = await _get_or_create(
            db,
            Accommodation,
            Accommodation.slug == _slug(f"demo {name}"),
            name=f"{name} (demo)",
            slug=_slug(f"demo {name}"),
            destination_id=diani.id,
            category=category,
            blurb=f"{name} is invented demo data used by the test suite.",
        )

    def _room(prop: Accommodation, label: str, occupancy: int) -> dict[str, Any]:
        return {
            "accommodation_id": prop.id,
            "name": label,
            "code": label[:3].upper(),
            "max_occupancy": occupancy,
        }

    rooms: dict[str, RoomType] = {}
    for key, prop, label, occupancy in (
        ("coral_twin", properties["Coral Shoals Resort"], "Twin", 2),
        ("coral_superior", properties["Coral Shoals Resort"], "Superior Twin", 2),
        ("mvule_twin", properties["Mvule Beach Lodge"], "Twin", 2),
        ("upepo_twin", properties["Upepo Guest House"], "Twin", 2),
        ("villa_two_bed", properties["Pendo Demo Villas"], "Two Bedroom", 4),
        ("chui_twin", properties["Chui Festive Camp"], "Twin", 2),
    ):
        rooms[key] = await _get_or_create(
            db,
            RoomType,
            (RoomType.accommodation_id == prop.id) & (RoomType.name == label),
            **_room(prop, label, occupancy),
        )

    async def _rate(
        room: RoomType,
        plan: MealPlan,
        rc: ResidenceCategory,
        amount: str,
        *,
        kind: str = "rack",
        discount: str | None = None,
        currency: str = "KES",
        child: str | None = None,
        child_bounds: tuple[int, int] | None = None,
        occupancy: int = 2,
        single_supplement: str | None = None,
        min_nights: int | None = None,
        season: tuple[str, date, date] = ("standard", SEASON_FROM, SEASON_TO),
    ) -> AccommodationRate:
        label, starts, ends = season
        return await _get_or_create(
            db,
            AccommodationRate,
            (AccommodationRate.room_type_id == room.id)
            & (AccommodationRate.meal_plan_id == plan.id)
            & (AccommodationRate.residence_category_id == rc.id)
            & (AccommodationRate.occupancy == occupancy)
            & (AccommodationRate.effective_from == starts),
            accommodation_id=room.accommodation_id,
            room_type_id=room.id,
            meal_plan_id=plan.id,
            residence_category_id=rc.id,
            season_name=f"{DEMO_MARKER} {label}",
            effective_from=starts,
            effective_to=ends,
            currency=currency,
            occupancy=occupancy,
            rate_per_night=Decimal(amount),
            child_rate=Decimal(child) if child else None,
            single_supplement=(
                Decimal(single_supplement) if single_supplement else None
            ),
            min_nights=min_nights,
            vat_inclusive=True,
            vat_pct=Decimal("16"),
            rate_kind=kind,
            supplier_discount_pct=Decimal(discount) if discount else None,
            child_min_age=child_bounds[0] if child_bounds else None,
            child_max_age=child_bounds[1] if child_bounds else None,
        )

    await _rate(rooms["coral_twin"], fb, citizen, "9000", kind="sto")
    await _rate(rooms["coral_superior"], fb, citizen, "12500", kind="sto")
    await _rate(rooms["coral_twin"], fb, citizen, "6500", kind="sto", occupancy=1)
    await _rate(rooms["coral_twin"], fb, non_resident, "180", kind="sto", currency="USD")

    await _rate(
        rooms["mvule_twin"], fb, citizen, "24000",
        kind="rack", discount="15", child="12000", child_bounds=(3, 11),
        single_supplement="4000",
    )

    await _rate(rooms["upepo_twin"], bb, citizen, "6000")

    await _rate(rooms["villa_two_bed"], hb, citizen, "16000", occupancy=4)

    await _rate(rooms["chui_twin"], fb, citizen, "14000")
    await _rate(
        rooms["chui_twin"], fb, citizen, "22000",
        min_nights=FESTIVE_MIN_NIGHTS,
        season=("festive", FESTIVE_FROM, FESTIVE_TO),
    )

    await _get_or_create(
        db,
        AccommodationSupplement,
        (AccommodationSupplement.accommodation_id
         == properties["Coral Shoals Resort"].id)
        & (AccommodationSupplement.label == f"{DEMO_MARKER} Christmas dinner")
        & (AccommodationSupplement.effective_from == SUPPLEMENT_FROM),
        accommodation_id=properties["Coral Shoals Resort"].id,
        label=f"{DEMO_MARKER} Christmas dinner",
        kind="gala",
        basis="per_person_per_night",
        amount=Decimal("2500"),
        currency="KES",
        effective_from=SUPPLEMENT_FROM,
        effective_to=SUPPLEMENT_TO,
        is_mandatory=True,
    )

    for rc, amount, currency in ((citizen, "1200", "KES"), (non_resident, "70", "USD")):
        await _get_or_create(
            db,
            ParkFee,
            (ParkFee.destination_id == mara.id)
            & (ParkFee.residence_category_id == rc.id)
            & (ParkFee.effective_from == SEASON_FROM),
            destination_id=mara.id,
            fee_type="park_entry",
            residence_category_id=rc.id,
            currency=currency,
            adult=Decimal(amount),
            child=Decimal(amount) / 2,
            infant=Decimal("0"),
            child_min_age=3,
            child_max_age=11,
            effective_from=SEASON_FROM,
            effective_to=SEASON_TO,
        )

    boat = await _get_or_create(
        db,
        Activity,
        Activity.slug == "demo-dhow-cruise",
        name="Dhow sunset cruise (demo)",
        slug="demo-dhow-cruise",
        destination_id=diani.id,
        duration_minutes=120,
        is_optional=False,
        is_mandatory=True,
    )
    quad = await _get_or_create(
        db,
        Activity,
        Activity.slug == "demo-quad-biking",
        name="Quad biking (demo)",
        slug="demo-quad-biking",
        destination_id=diani.id,
        is_optional=True,
        has_own_section=True,
    )
    for activity, adult, child in ((boat, "3500", "1800"), (quad, "2500", "2500")):
        await _get_or_create(
            db,
            ActivityRate,
            (ActivityRate.activity_id == activity.id)
            & (ActivityRate.residence_category_id == citizen.id)
            & (ActivityRate.effective_from == SEASON_FROM),
            activity_id=activity.id,
            residence_category_id=citizen.id,
            currency="KES",
            adult_price=Decimal(adult),
            child_price=Decimal(child),
            effective_from=SEASON_FROM,
            effective_to=SEASON_TO,
        )
    for label, minutes, price, order in (
        ("10 minutes", 10, "1500", 1),
        ("15 minutes", 15, "2000", 2),
        ("30 minutes", 30, "3500", 3),
    ):
        await _get_or_create(
            db,
            ActivityPriceTier,
            (ActivityPriceTier.activity_id == quad.id)
            & (ActivityPriceTier.residence_category_id == citizen.id)
            & (ActivityPriceTier.label == label)
            & (ActivityPriceTier.effective_from == SEASON_FROM),
            activity_id=quad.id,
            residence_category_id=citizen.id,
            label=label,
            duration_minutes=minutes,
            price=Decimal(price),
            currency="KES",
            effective_from=SEASON_FROM,
            effective_to=SEASON_TO,
            sort_order=order,
        )

    fuel_type = "demo-diesel"
    coaster = await _get_or_create(
        db,
        Vehicle,
        Vehicle.slug == "demo-coaster",
        name="Coaster 25-seater (demo)",
        slug="demo-coaster",
        vehicle_type="minibus",
        passenger_capacity=25,
        fuel_type=fuel_type,
        fuel_consumption_kmpl=Decimal("6"),
        daily_operating_cost=Decimal("4000"),
        driver_cost_per_day=Decimal("3000"),
        currency="KES",
    )
    await _get_or_create(
        db,
        FuelPrice,
        (FuelPrice.fuel_type == fuel_type) & (FuelPrice.effective_from == SEASON_FROM),
        fuel_type=fuel_type,
        price_per_litre=Decimal("185"),
        currency="KES",
        effective_from=SEASON_FROM,
    )

    for travel_class, fare in (("economy", "1500"), ("business", "12000")):
        await _get_or_create(
            db,
            DestinationTransportMode,
            (DestinationTransportMode.destination_id == diani.id)
            & (DestinationTransportMode.mode == "rail")
            & (DestinationTransportMode.travel_class == travel_class)
            & (DestinationTransportMode.effective_from == SEASON_FROM),
            destination_id=diani.id,
            mode="rail",
            travel_class=travel_class,
            label=f"SGR {travel_class} (demo)",
            cost_basis="per_person",
            price=Decimal(fare),
            currency="KES",
            effective_from=SEASON_FROM,
        )
    for vehicle_type, price in (("minibus", "12000"), ("saloon", "4500")):
        await _get_or_create(
            db,
            TransferRate,
            (TransferRate.destination_id == diani.id)
            & (TransferRate.vehicle_type == vehicle_type)
            & (TransferRate.route_label == "Terminus to hotel")
            & (TransferRate.effective_from == SEASON_FROM),
            destination_id=diani.id,
            vehicle_type=vehicle_type,
            route_label="Terminus to hotel",
            price_per_leg=Decimal(price),
            currency="KES",
            effective_from=SEASON_FROM,
        )

    await db.commit()

    return {
        "destination_diani": str(diani.id),
        "destination_mara": str(mara.id),
        "residence_citizen": str(citizen.id),
        "residence_non_resident": str(non_resident.id),
        "meal_plan_bb": str(bb.id),
        "meal_plan_hb": str(hb.id),
        "meal_plan_fb": str(fb.id),
        "acc_sto_full_board": str(properties["Coral Shoals Resort"].id),
        "acc_rack_discounted": str(properties["Mvule Beach Lodge"].id),
        "acc_bb_only": str(properties["Upepo Guest House"].id),
        "acc_villa": str(properties["Pendo Demo Villas"].id),
        "acc_min_stay": str(properties["Chui Festive Camp"].id),
        "room_coral_twin": str(rooms["coral_twin"].id),
        "room_coral_superior": str(rooms["coral_superior"].id),
        "room_mvule_twin": str(rooms["mvule_twin"].id),
        "room_upepo_twin": str(rooms["upepo_twin"].id),
        "room_villa": str(rooms["villa_two_bed"].id),
        "room_chui_twin": str(rooms["chui_twin"].id),
        "activity_mandatory": str(boat.id),
        "activity_optional": str(quad.id),
        "vehicle_coaster": str(coaster.id),
        "fuel_type": fuel_type,
        "season_from": SEASON_FROM.isoformat(),
        "season_to": SEASON_TO.isoformat(),
        "festive_from": FESTIVE_FROM.isoformat(),
        "festive_to": FESTIVE_TO.isoformat(),
        "festive_min_nights": FESTIVE_MIN_NIGHTS,
        "supplement_from": SUPPLEMENT_FROM.isoformat(),
        "supplement_to": SUPPLEMENT_TO.isoformat(),
    }


_PUBLIC_TIER_STARS = {
    "acc_bb_only": 2,
    "acc_sto_full_board": 4,
    "acc_rack_discounted": 5,
}


async def publish_public_demo(db: AsyncSession, ids: dict[str, Any]) -> None:
    from app.modules.accommodations.models import Accommodation
    from app.modules.destinations.models import Destination
    from app.modules.public.service import DESTINATION, PROPERTY, PublishService

    diani_id = uuid.UUID(ids["destination_diani"])
    diani = (
        await db.execute(select(Destination).where(Destination.id == diani_id))
    ).scalar_one()
    if not (diani.description or "").strip():
        diani.description = (
            f"{diani.name}: a stretch of coast used by the demo catalogue to "
            f"exercise the public site and safari builder end to end."
        )

    for key, rating in _PUBLIC_TIER_STARS.items():
        acc = (
            await db.execute(select(Accommodation).where(Accommodation.id == uuid.UUID(ids[key])))
        ).scalar_one()
        acc.star_rating = rating
    await db.commit()

    pub = PublishService(db)
    await pub.publish(DESTINATION, diani.id)
    for key in _PUBLIC_TIER_STARS:
        await pub.publish(PROPERTY, uuid.UUID(ids[key]))


async def _main() -> None:
    uri = settings.sqlalchemy_sync_uri
    target = uri.split("@")[-1].split("?")[0]
    print(f"[seed_demo] target database: {target}")
    if "--yes" not in sys.argv:
        print(
            "[seed_demo] refusing to run without --yes.\n"
            "            This loads INVENTED hotel rates. Never load it into the\n"
            "            live catalogue: a fabricated rate could reach a client."
        )
        raise SystemExit(1)
    async with AsyncSessionLocal() as db:
        ids = await seed_demo(db)
        if "--publish" in sys.argv:
            await publish_public_demo(db, ids)
    print(f"[seed_demo] done — {len(ids)} reference ids available")
    if "--publish" in sys.argv:
        print(
            "[seed_demo] published demo-diani + 3 demo properties "
            "(comfort/luxury/ultra) for the public site and /builder"
        )


if __name__ == "__main__":
    asyncio.run(_main())
