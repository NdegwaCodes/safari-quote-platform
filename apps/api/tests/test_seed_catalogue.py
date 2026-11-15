from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.modules.accommodations.models import AccommodationRate, RoomType
from app.modules.activities.models import ActivityPriceTier
from app.modules.transport.models import DestinationTransportMode, TransferRate

pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal


async def test_seed_is_idempotent(sample_catalogue):
    from app.db.seed_demo import seed_demo

    async with AsyncSessionLocal() as db:
        second = await seed_demo(db)
    assert second == sample_catalogue


async def test_sto_and_discounted_rack_rates_coexist(sample_catalogue):
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AccommodationRate).where(
                    AccommodationRate.room_type_id.in_(
                        [
                            sample_catalogue["room_coral_twin"],
                            sample_catalogue["room_mvule_twin"],
                        ]
                    )
                )
            )
        ).scalars().all()

    by_kind = {r.rate_kind for r in rows}
    assert by_kind == {"sto", "rack"}

    sto = next(r for r in rows if r.rate_kind == "sto")
    rack = next(r for r in rows if r.rate_kind == "rack")

    assert all(r.vat_inclusive for r in rows)
    assert all(r.vat_pct == D("16") for r in rows)

    assert sto.supplier_discount_pct is None
    assert rack.supplier_discount_pct == D("15.000")
    assert rack.rate_per_night == D("24000.0000")


async def test_child_policy_is_per_property(sample_catalogue):
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AccommodationRate).where(
                    AccommodationRate.room_type_id.in_(
                        [
                            sample_catalogue["room_mvule_twin"],
                            sample_catalogue["room_coral_twin"],
                        ]
                    )
                )
            )
        ).scalars().all()

    with_policy = [r for r in rows if r.child_min_age is not None]
    without_policy = [r for r in rows if r.child_min_age is None]
    assert with_policy and without_policy, "need both cases to test the default"

    policy = with_policy[0]
    assert (policy.child_min_age, policy.child_max_age) == (3, 11)
    assert policy.child_rate == D("12000.0000")
    assert without_policy[0].child_rate is None


async def test_resident_and_non_resident_rates_both_exist(sample_catalogue):
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AccommodationRate).where(
                    AccommodationRate.room_type_id == sample_catalogue["room_coral_twin"]
                )
            )
        ).scalars().all()

    by_rc = {str(r.residence_category_id): r for r in rows}
    assert sample_catalogue["residence_citizen"] in by_rc
    assert sample_catalogue["residence_non_resident"] in by_rc
    assert by_rc[sample_catalogue["residence_citizen"]].currency == "KES"
    assert by_rc[sample_catalogue["residence_non_resident"]].currency == "USD"


async def test_bed_and_breakfast_only_property_has_no_board_rates(sample_catalogue):
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(AccommodationRate).where(
                    AccommodationRate.room_type_id == sample_catalogue["room_upepo_twin"]
                )
            )
        ).scalars().all()

    assert len(rows) == 1
    assert str(rows[0].meal_plan_id) == sample_catalogue["meal_plan_bb"]


async def test_villa_capacity_drives_rooming(sample_catalogue):
    async with AsyncSessionLocal() as db:
        villa = (
            await db.execute(
                select(RoomType).where(RoomType.id == sample_catalogue["room_villa"])
            )
        ).scalar_one()
        twin = (
            await db.execute(
                select(RoomType).where(RoomType.id == sample_catalogue["room_coral_twin"])
            )
        ).scalar_one()

    assert villa.max_occupancy == 4
    assert twin.max_occupancy == 2
    assert -(-25 // villa.max_occupancy) == 7
    assert -(-25 // twin.max_occupancy) == 13


async def test_activity_price_tiers_form_an_ascending_ladder(sample_catalogue):
    async with AsyncSessionLocal() as db:
        tiers = (
            await db.execute(
                select(ActivityPriceTier)
                .where(ActivityPriceTier.activity_id == sample_catalogue["activity_optional"])
                .order_by(ActivityPriceTier.sort_order)
            )
        ).scalars().all()

    assert [t.label for t in tiers] == ["10 minutes", "15 minutes", "30 minutes"]
    assert [t.duration_minutes for t in tiers] == [10, 15, 30]
    prices = [t.price for t in tiers]
    assert prices == sorted(prices), "a longer ride must not cost less"
    assert all(t.vat_inclusive for t in tiers)


async def test_rail_fares_are_rows_not_constants(sample_catalogue):
    async with AsyncSessionLocal() as db:
        modes = (
            await db.execute(
                select(DestinationTransportMode).where(
                    DestinationTransportMode.destination_id
                    == sample_catalogue["destination_diani"]
                )
            )
        ).scalars().all()

    fares = {m.travel_class: m for m in modes}
    assert fares["economy"].price == D("1500.0000")
    assert fares["business"].price == D("12000.0000")
    for m in modes:
        assert m.mode == "rail"
        assert m.cost_basis == "per_person"
        assert m.effective_from == date(2026, 1, 1)
    assert fares["economy"].price * 25 * 2 == D("75000")


async def test_air_is_never_an_offerable_mode(sample_catalogue):
    async with AsyncSessionLocal() as db:
        modes = (await db.execute(select(DestinationTransportMode))).scalars().all()
    assert modes, "expected seeded transport modes"
    assert all(m.mode != "air" for m in modes)


async def test_transfer_price_depends_on_vehicle_type(sample_catalogue):
    async with AsyncSessionLocal() as db:
        rates = (
            await db.execute(
                select(TransferRate).where(
                    TransferRate.destination_id == sample_catalogue["destination_diani"],
                    TransferRate.route_label == "Terminus to hotel",
                )
            )
        ).scalars().all()

    by_vehicle = {r.vehicle_type: r.price_per_leg for r in rates}
    assert by_vehicle["minibus"] == D("12000.0000")
    assert by_vehicle["saloon"] == D("4500.0000")
    assert by_vehicle["minibus"] != by_vehicle["saloon"]
    assert all(r.route_label for r in rates)
