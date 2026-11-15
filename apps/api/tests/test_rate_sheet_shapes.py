from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.session import AsyncSessionLocal
from app.modules.accommodations.models import (
    SUPPLEMENT_BASES,
    SUPPLEMENT_KINDS,
    Accommodation,
    AccommodationRate,
    AccommodationSupplement,
    MealPlan,
    RoomType,
)
from app.modules.currency.fx import AdminExchangeRateProvider
from app.modules.currency.models import ExchangeRate
from app.modules.destinations.models import Destination
from app.modules.residence.models import ResidenceCategory

pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal
HIGH_FROM, HIGH_TO = date(2027, 1, 11), date(2027, 12, 19)
FESTIVE_FROM, FESTIVE_TO = date(2027, 12, 20), date(2028, 1, 10)


@pytest_asyncio.fixture(loop_scope="session")
async def throwaway_property():
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        dest = (await db.execute(select(Destination).limit(1))).scalar_one()
        fb = (await db.execute(select(MealPlan).where(MealPlan.code == "FB"))).scalar_one()
        rc = (
            await db.execute(
                select(ResidenceCategory).where(ResidenceCategory.key == "citizen")
            )
        ).scalar_one()

        acc = Accommodation(
            name=f"Sheet Shapes Test {tag}",
            slug=f"sheet-shapes-{tag}",
            destination_id=dest.id,
            category="resort",
        )
        db.add(acc)
        await db.flush()
        room = RoomType(
            accommodation_id=acc.id, name="Creek Deluxe", code="CRK", max_occupancy=3
        )
        db.add(room)
        await db.flush()
        ids = {
            "accommodation_id": acc.id,
            "room_type_id": room.id,
            "meal_plan_id": fb.id,
            "residence_category_id": rc.id,
        }
        await db.commit()

    yield ids

    async with AsyncSessionLocal() as db:
        acc = await db.get(Accommodation, ids["accommodation_id"])
        if acc is not None:
            await db.delete(acc)
            await db.commit()


def _rate(ids: dict, occupancy: int, amount: str, **kw) -> AccommodationRate:
    return AccommodationRate(
        accommodation_id=ids["accommodation_id"],
        room_type_id=ids["room_type_id"],
        meal_plan_id=ids["meal_plan_id"],
        residence_category_id=ids["residence_category_id"],
        season_name="HIGH",
        occupancy=occupancy,
        effective_from=HIGH_FROM,
        effective_to=HIGH_TO,
        currency="KES",
        rate_per_night=D(amount),
        **kw,
    )


async def test_one_room_and_season_holds_a_price_per_occupancy(throwaway_property):
    async with AsyncSessionLocal() as db:
        for occ, amount in ((1, "28400"), (2, "37600"), (3, "44000")):
            db.add(_rate(throwaway_property, occ, amount, rate_kind="sto"))
        await db.commit()

        rows = (
            await db.execute(
                select(AccommodationRate)
                .where(AccommodationRate.room_type_id == throwaway_property["room_type_id"])
                .order_by(AccommodationRate.occupancy)
            )
        ).scalars().all()

    assert [r.occupancy for r in rows] == [1, 2, 3]
    assert [r.rate_per_night for r in rows] == [D("28400"), D("37600"), D("44000")]
    single, double = rows[0].rate_per_night, rows[1].rate_per_night
    assert single < double < single * 2


async def test_same_occupancy_twice_is_still_rejected(throwaway_property):
    async with AsyncSessionLocal() as db:
        db.add(_rate(throwaway_property, 2, "37600"))
        await db.commit()
        db.add(_rate(throwaway_property, 2, "99999"))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


async def test_occupancy_defaults_to_two(throwaway_property):
    async with AsyncSessionLocal() as db:
        r = AccommodationRate(
            accommodation_id=throwaway_property["accommodation_id"],
            room_type_id=throwaway_property["room_type_id"],
            meal_plan_id=throwaway_property["meal_plan_id"],
            residence_category_id=throwaway_property["residence_category_id"],
            effective_from=HIGH_FROM,
            effective_to=HIGH_TO,
            currency="KES",
            rate_per_night=D("37600"),
        )
        db.add(r)
        await db.commit()
        await db.refresh(r)
        assert r.occupancy == 2


async def test_festive_supplement_is_storable_with_its_own_window(throwaway_property):
    async with AsyncSessionLocal() as db:
        db.add(
            AccommodationSupplement(
                accommodation_id=throwaway_property["accommodation_id"],
                label="Supplement Christmas",
                kind="festive",
                basis="per_person_per_night",
                amount=D("3300"),
                currency="KES",
                effective_from=date(2027, 12, 24),
                effective_to=date(2027, 12, 25),
                is_mandatory=True,
            )
        )
        await db.commit()

        s = (
            await db.execute(
                select(AccommodationSupplement).where(
                    AccommodationSupplement.accommodation_id
                    == throwaway_property["accommodation_id"],
                    AccommodationSupplement.label == "Supplement Christmas",
                )
            )
        ).scalar_one()

    assert s.kind in SUPPLEMENT_KINDS
    assert s.basis in SUPPLEMENT_BASES
    assert s.is_mandatory is True
    assert (s.vat_inclusive, s.vat_pct) == (True, D("16.00"))
    assert FESTIVE_FROM <= s.effective_from and s.effective_to <= FESTIVE_TO
    assert not (HIGH_FROM <= s.effective_from <= HIGH_TO)
    assert (s.effective_to - s.effective_from).days + 1 == 2
    assert s.amount * 25 * 2 == D("165000")


async def test_supplement_applies_property_wide_when_room_is_null(throwaway_property):
    async with AsyncSessionLocal() as db:
        db.add(
            AccommodationSupplement(
                accommodation_id=throwaway_property["accommodation_id"],
                label="Gala Dinner New Year",
                kind="gala",
                basis="per_person",
                amount=D("3300"),
                currency="KES",
                effective_from=date(2027, 12, 31),
                effective_to=date(2028, 1, 1),
            )
        )
        await db.commit()
        s = (
            await db.execute(
                select(AccommodationSupplement).where(
                    AccommodationSupplement.label == "Gala Dinner New Year",
                    AccommodationSupplement.accommodation_id
                    == throwaway_property["accommodation_id"],
                )
            )
        ).scalar_one()

    assert (s.room_type_id, s.meal_plan_id, s.residence_category_id) == (None, None, None)
    assert s.is_mandatory is True
    assert s.basis == "per_person"


async def test_contract_fx_rate_is_seeded_not_only_set_up_by_tests():
    async with AsyncSessionLocal() as db:
        seeded = (
            await db.execute(
                select(ExchangeRate).where(
                    ExchangeRate.base_currency == "USD",
                    ExchangeRate.quote_currency == "KES",
                    ExchangeRate.source == "contract",
                )
            )
        ).scalars().all()
        assert seeded, "the contract USD->KES rate is not seeded"
        assert seeded[0].rate == D("130")


async def test_fx_is_deterministic_when_two_rates_share_a_date():
    async with AsyncSessionLocal() as db:
        fx = AdminExchangeRateProvider(db)
        first = ExchangeRate(
            base_currency="USD",
            quote_currency="ZZZ",
            rate=D("100"),
            effective_from=date(2026, 1, 1),
            source="test",
        )
        db.add(first)
        await db.commit()
        assert await fx.effective_rate("USD", "ZZZ", date(2026, 6, 1)) == D("100")

        later = ExchangeRate(
            base_currency="USD",
            quote_currency="ZZZ",
            rate=D("111"),
            effective_from=date(2026, 1, 1),
            source="test",
        )
        db.add(later)
        await db.commit()
        try:
            got = await fx.effective_rate("USD", "ZZZ", date(2026, 6, 1))
            assert got == D("111"), "the later entry for the same day must win"
        finally:
            await db.delete(later)
            await db.delete(first)
            await db.commit()
