from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.db.seed_park_fees import (
    KWS_CATEGORIES,
    KWS_CHILD_MAX,
    KWS_CHILD_MIN,
    KWS_PARKS,
    MICE_SOURCE_NOTE,
    VEHICLE_DAY_CHARGES_KES,
    seed_park_fees,
)
from app.db.session import AsyncSessionLocal
from app.modules.destinations.models import Destination
from app.modules.park_fees.models import ParkFee
from app.modules.park_fees.service import classify_age, compute_park_fee
from app.modules.residence.models import ResidenceCategory

pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal


async def _fee(db, park_slug: str, residence_key: str, on: date) -> ParkFee:
    destination = (
        await db.execute(select(Destination).where(Destination.slug == park_slug))
    ).scalar_one()
    residence = (
        await db.execute(
            select(ResidenceCategory).where(ResidenceCategory.key == residence_key)
        )
    ).scalar_one()
    return (
        await db.execute(
            select(ParkFee).where(
                ParkFee.destination_id == destination.id,
                ParkFee.residence_category_id == residence.id,
                ParkFee.effective_from <= on,
                ParkFee.effective_to >= on,
            )
        )
    ).scalar_one()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def park_fees():
    async with AsyncSessionLocal() as db:
        return await seed_park_fees(db)


async def test_the_schedule_seeds_every_park_and_is_idempotent(park_fees):
    assert park_fees["destinations"] == len(KWS_PARKS) + 1
    async with AsyncSessionLocal() as db:
        again = await seed_park_fees(db)
    assert again["fees_created"] == 0
    assert again["fees_corrected"] == 0
    assert again["fees_unchanged"] > 0


async def test_a_wrong_figure_on_file_is_corrected_not_skipped(park_fees):
    async with AsyncSessionLocal() as db:
        fee = await _fee(db, "amboseli-national-park", "citizen", date(2026, 7, 1))
        fee.adult = D("999999")
        fee.currency = "USD"
        await db.commit()

        result = await seed_park_fees(db)
        assert result["fees_corrected"] == 1

        fixed = await _fee(db, "amboseli-national-park", "citizen", date(2026, 7, 1))
        assert fixed.adult == D("1500")
        assert fixed.currency == "KES"


async def test_amboseli_premium_park_fees(park_fees):
    on = date(2026, 7, 1)
    async with AsyncSessionLocal() as db:
        citizen = await _fee(db, "amboseli-national-park", "citizen", on)
        resident = await _fee(db, "amboseli-national-park", "resident", on)
        non_resident = await _fee(db, "amboseli-national-park", "non_resident", on)
        african = await _fee(db, "amboseli-national-park", "african_citizen", on)

    assert (citizen.adult, citizen.child, citizen.currency) == (D("1500"), D("750"), "KES")
    assert (resident.adult, resident.child, resident.currency) == (
        D("2025"), D("1050"), "KES",
    )
    assert (non_resident.adult, non_resident.child, non_resident.currency) == (
        D("90"), D("45"), "USD",
    )
    assert (african.adult, african.child, african.currency) == (D("50"), D("25"), "USD")


async def test_an_african_citizen_is_charged_far_less_than_a_non_resident(park_fees):
    on = date(2026, 7, 1)
    async with AsyncSessionLocal() as db:
        african = await _fee(db, "amboseli-national-park", "african_citizen", on)
        non_resident = await _fee(db, "amboseli-national-park", "non_resident", on)
    assert african.adult < non_resident.adult
    assert african.adult == D("50")


async def test_a_kenya_resident_is_charged_in_shillings_not_dollars(park_fees):
    async with AsyncSessionLocal() as db:
        resident = await _fee(db, "amboseli-national-park", "resident", date(2026, 7, 1))
    assert resident.currency == "KES"
    assert resident.adult == D("2025")


async def test_the_marine_parks_the_reference_proposal_needs(park_fees):
    async with AsyncSessionLocal() as db:
        citizen = await _fee(
            db, "kisite-mpunguti-marine-national-park", "citizen", date(2026, 7, 1)
        )
        non_resident = await _fee(
            db, "kisite-mpunguti-marine-national-park", "non_resident", date(2026, 7, 1)
        )
    assert citizen.adult == D("500")
    assert non_resident.adult == D("25")


async def test_child_bounds_encode_the_exemption(park_fees):
    assert (KWS_CHILD_MIN, KWS_CHILD_MAX) == (6, 17)
    async with AsyncSessionLocal() as db:
        fee = await _fee(db, "amboseli-national-park", "citizen", date(2026, 7, 1))
    assert (fee.child_min_age, fee.child_max_age) == (6, 17)
    assert fee.infant == 0
    assert classify_age(5, fee.child_min_age, fee.child_max_age) == "infant"
    assert classify_age(6, fee.child_min_age, fee.child_max_age) == "child"
    assert classify_age(17, fee.child_min_age, fee.child_max_age) == "child"
    assert classify_age(18, fee.child_min_age, fee.child_max_age) == "adult"


async def test_the_mara_doubles_between_its_seasons(park_fees):
    async with AsyncSessionLocal() as db:
        green = await _fee(
            db, "maasai-mara-national-reserve", "non_resident", date(2026, 3, 15)
        )
        peak = await _fee(
            db, "maasai-mara-national-reserve", "non_resident", date(2026, 9, 15)
        )
    assert green.adult == D("100")
    assert peak.adult == D("200")
    assert peak.adult == green.adult * 2


async def test_the_mara_child_band_differs_by_residence(park_fees):
    async with AsyncSessionLocal() as db:
        citizen = await _fee(
            db, "maasai-mara-national-reserve", "citizen", date(2026, 9, 15)
        )
        non_resident = await _fee(
            db, "maasai-mara-national-reserve", "non_resident", date(2026, 9, 15)
        )
    assert citizen.child_min_age == 3
    assert non_resident.child_min_age == 9
    assert classify_age(8, non_resident.child_min_age, non_resident.child_max_age) == "infant"
    assert classify_age(8, citizen.child_min_age, citizen.child_max_age) == "child"


async def test_a_kws_park_is_not_seasonal(park_fees):
    async with AsyncSessionLocal() as db:
        january = await _fee(db, "tsavo-east-national-park", "citizen", date(2026, 1, 5))
        august = await _fee(db, "tsavo-east-national-park", "citizen", date(2026, 8, 5))
    assert january.id == august.id
    assert january.adult == D("1000")


async def test_a_mixed_family_in_the_mara_in_peak_season(park_fees):
    async with AsyncSessionLocal() as db:
        fee = await _fee(
            db, "maasai-mara-national-reserve", "non_resident", date(2026, 9, 15)
        )
    result = compute_park_fee(
        adult_fee=fee.adult,
        child_fee=fee.child,
        infant_fee=fee.infant,
        adults=2,
        ages=[8, 12],
        days=3,
        child_min_age=fee.child_min_age,
        child_max_age=fee.child_max_age,
    )
    assert result["counts"] == {"adult": 2, "child": 1, "infant": 1}
    assert result["adult_total"] == D("1200")
    assert result["child_total"] == D("150")
    assert result["total"] == D("1350")


async def test_a_twenty_five_pax_group_owes_real_money_in_park_fees(park_fees):
    async with AsyncSessionLocal() as db:
        fee = await _fee(db, "amboseli-national-park", "citizen", date(2026, 7, 1))
    result = compute_park_fee(
        adult_fee=fee.adult,
        child_fee=fee.child,
        infant_fee=fee.infant,
        adults=25,
        ages=[],
        days=2,
        child_min_age=fee.child_min_age,
        child_max_age=fee.child_max_age,
    )
    assert result["total"] == D("75000")


def test_the_vehicle_seat_bands_are_recorded_for_transport_costing():
    bands = {(low, high): amount for low, high, amount in VEHICLE_DAY_CHARGES_KES}
    assert bands[(25, 44)] == "4500"
    assert bands[(6, 12)] == "1500"
    ordered = sorted(VEHICLE_DAY_CHARGES_KES)
    for (_, high, _), (low, _, _) in zip(ordered, ordered[1:], strict=False):
        assert low == high + 1


def test_the_group_discount_reading_is_written_down_not_assumed():
    assert "ambiguous" in MICE_SOURCE_NOTE.lower()


def test_every_kws_category_prices_every_residence():
    expected = {"citizen", "ea_resident", "resident", "non_resident", "african_citizen"}
    for name, table in KWS_CATEGORIES.items():
        assert set(table) == expected, name
        for residence, (adult, child, currency) in table.items():
            assert Decimal(adult) > 0, (name, residence)
            assert Decimal(child) > 0, (name, residence)
            assert Decimal(child) < Decimal(adult), (name, residence)
            expected_ccy = (
                "KES" if residence in {"citizen", "ea_resident", "resident"} else "USD"
            )
            assert currency == expected_ccy, (name, residence)
