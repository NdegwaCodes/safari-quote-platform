from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.modules.accommodations.models import (
    Accommodation,
    AccommodationRate,
    MealPlan,
    RoomType,
)
from app.modules.destinations.models import Destination
from app.modules.park_fees.models import ParkFee
from app.modules.quotes.models import Quote, QuoteOption
from app.modules.residence.models import ResidenceCategory
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal

ARRIVAL, DEPARTURE = "2026-07-01", "2026-07-04"
LOW_FROM, LOW_TO = date(2026, 1, 1), date(2026, 7, 31)
HIGH_FROM, HIGH_TO = date(2026, 8, 1), date(2026, 12, 31)

RESIDENT_LOW, RESIDENT_HIGH = D("1000"), D("1500")
VISITOR_LOW, VISITOR_HIGH = D("60"), D("80")
USD_KES = D("130")


@pytest_asyncio.fixture(loop_scope="session")
async def safari_camp():
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        fb = (
            await db.execute(select(MealPlan).where(MealPlan.code == "FB"))
        ).scalar_one()
        citizen = (
            await db.execute(
                select(ResidenceCategory).where(ResidenceCategory.key == "citizen")
            )
        ).scalar_one()
        visitor = (
            await db.execute(
                select(ResidenceCategory).where(
                    ResidenceCategory.key == "non_resident"
                )
            )
        ).scalar_one()

        park = Destination(
            name=f"Test Conservation Area {tag}",
            slug=f"test-park-{tag}",
            type="park",
        )
        db.add(park)
        await db.flush()

        camp = Accommodation(
            name=f"Fee Test Camp {tag}",
            slug=f"fee-test-camp-{tag}",
            destination_id=park.id,
            category="camp",
        )
        db.add(camp)
        await db.flush()
        tent = RoomType(
            accommodation_id=camp.id, name="Tent", code="TNT", max_occupancy=2
        )
        db.add(tent)
        await db.flush()

        for rc, amount, currency in (
            (citizen, "20000", "KES"),
            (visitor, "200", "USD"),
        ):
            for occupancy, share in ((2, D(1)), (1, D("0.75"))):
                db.add(
                    AccommodationRate(
                        accommodation_id=camp.id,
                        room_type_id=tent.id,
                        meal_plan_id=fb.id,
                        residence_category_id=rc.id,
                        season_name="standard",
                        occupancy=occupancy,
                        effective_from=LOW_FROM,
                        effective_to=HIGH_TO,
                        currency=currency,
                        rate_per_night=(D(amount) * share),
                        rate_kind="sto",
                    )
                )

        for rc, currency, low, high in (
            (citizen, "KES", RESIDENT_LOW, RESIDENT_HIGH),
            (visitor, "USD", VISITOR_LOW, VISITOR_HIGH),
        ):
            for amount, starts, ends in (
                (low, LOW_FROM, LOW_TO),
                (high, HIGH_FROM, HIGH_TO),
            ):
                db.add(
                    ParkFee(
                        destination_id=park.id,
                        fee_type="park_entry",
                        residence_category_id=rc.id,
                        currency=currency,
                        adult=amount,
                        child=amount / 2,
                        infant=D(0),
                        child_min_age=6,
                        child_max_age=17,
                        effective_from=starts,
                        effective_to=ends,
                    )
                )
        await db.commit()
        ids = {
            "destination_id": str(park.id),
            "accommodation_id": str(camp.id),
            "citizen": str(citizen.id),
            "non_resident": str(visitor.id),
            "meal_plan_fb": str(fb.id),
        }

    yield ids

    async with AsyncSessionLocal() as db:
        quote_ids = (
            (
                await db.execute(
                    select(QuoteOption.quote_id).where(
                        QuoteOption.accommodation_id
                        == uuid.UUID(ids["accommodation_id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        for quote_id in set(quote_ids):
            quote = await db.get(Quote, quote_id)
            if quote is not None:
                await db.delete(quote)
        await db.flush()

        park_row = await db.get(Destination, uuid.UUID(ids["destination_id"]))
        camp_row = await db.get(Accommodation, uuid.UUID(ids["accommodation_id"]))
        if camp_row is not None:
            await db.delete(camp_row)
            await db.flush()
        if park_row is not None:
            await db.delete(park_row)
        await db.commit()


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _priced(client, h, camp, *, cohorts, arrival=ARRIVAL, departure=DEPARTURE):
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Park Fee Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("parkfee"),
            "residence_category_id": camp["citizen"],
        },
    )
    assert record.status_code == 201, record.text
    quote = await client.post(
        f"{API}/quotes",
        headers=h,
        json={
            "client_id": record.json()["id"],
            "presentation_currency": "KES",
            "residence_category_id": camp["citizen"],
            "arrival_date": arrival,
            "departure_date": departure,
            "requested_meal_plan_id": camp["meal_plan_fb"],
            "cohorts": [
                {
                    "residence_category_id": camp[residence],
                    "traveller_type": kind,
                    "headcount": n,
                }
                for residence, kind, n in cohorts
            ],
            "options": [{"accommodation_id": camp["accommodation_id"]}],
        },
    )
    assert quote.status_code == 201, quote.text
    priced = await client.post(
        f"{API}/quotes/{quote.json()['id']}/options/price", headers=h
    )
    assert priced.status_code == 200, priced.text
    body = priced.json()
    assert len(body["options"]) == 1, body
    return body["options"][0]


async def test_park_fees_reach_the_option_build_up(client, admin_tokens, safari_camp):
    option = await _priced(
        client, _h(admin_tokens), safari_camp, cohorts=[("citizen", "adult", 4)]
    )
    components = option["build_up"]["components"]
    assert "park_fees" in components, components
    assert D(components["park_fees"]) == D("12000")


async def test_a_child_pays_the_child_fee(client, admin_tokens, safari_camp):
    option = await _priced(
        client,
        _h(admin_tokens),
        safari_camp,
        cohorts=[("citizen", "adult", 2), ("citizen", "child", 2)],
    )
    assert D(option["build_up"]["components"]["park_fees"]) == D("9000")


async def test_each_residency_pays_its_own_schedule(client, admin_tokens, safari_camp):
    option = await _priced(
        client,
        _h(admin_tokens),
        safari_camp,
        cohorts=[("citizen", "adult", 2), ("non_resident", "adult", 2)],
    )
    expected = D(2) * RESIDENT_LOW * 3 + D(2) * VISITOR_LOW * 3 * USD_KES
    assert D(option["build_up"]["components"]["park_fees"]) == expected


async def test_a_stay_crossing_a_fee_season_is_charged_per_night(
    client, admin_tokens, safari_camp
):
    option = await _priced(
        client,
        _h(admin_tokens),
        safari_camp,
        cohorts=[("citizen", "adult", 1)],
        arrival="2026-07-30",
        departure="2026-08-02",
    )
    assert D(option["build_up"]["components"]["park_fees"]) == D("3500")


async def test_a_destination_that_charges_nothing_adds_no_component(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"No Park Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("nopark"),
            "residence_category_id": ids["residence_citizen"],
        },
    )
    quote = await client.post(
        f"{API}/quotes",
        headers=h,
        json={
            "client_id": record.json()["id"],
            "presentation_currency": "KES",
            "residence_category_id": ids["residence_citizen"],
            "arrival_date": ARRIVAL,
            "departure_date": DEPARTURE,
            "pax_count": 4,
            "requested_meal_plan_id": ids["meal_plan_fb"],
            "options": [{"accommodation_id": ids["acc_sto_full_board"]}],
        },
    )
    assert quote.status_code == 201, quote.text
    priced = await client.post(
        f"{API}/quotes/{quote.json()['id']}/options/price", headers=h
    )
    option = priced.json()["options"][0]
    assert "park_fees" not in option["build_up"]["components"]


async def test_a_residency_with_no_fee_on_file_is_warned_about(
    client, admin_tokens, safari_camp
):
    h = _h(admin_tokens)
    async with AsyncSessionLocal() as db:
        ea = (
            await db.execute(
                select(ResidenceCategory).where(ResidenceCategory.key == "ea_resident")
            )
        ).scalar_one()
        fb = uuid.UUID(safari_camp["meal_plan_fb"])
        db.add(
            AccommodationRate(
                accommodation_id=uuid.UUID(safari_camp["accommodation_id"]),
                room_type_id=(
                    await db.execute(
                        select(RoomType.id).where(
                            RoomType.accommodation_id
                            == uuid.UUID(safari_camp["accommodation_id"])
                        )
                    )
                ).scalar_one(),
                meal_plan_id=fb,
                residence_category_id=ea.id,
                season_name="standard",
                occupancy=2,
                effective_from=LOW_FROM,
                effective_to=HIGH_TO,
                currency="KES",
                rate_per_night=D("18000"),
                rate_kind="sto",
            )
        )
        await db.commit()
        camp = dict(safari_camp, ea_resident=str(ea.id))

    option = await _priced(
        client,
        h,
        camp,
        cohorts=[("citizen", "adult", 2), ("ea_resident", "adult", 2)],
    )
    assert D(option["build_up"]["components"]["park_fees"]) == D(2) * RESIDENT_LOW * 3
    assert any(
        "none is on file for ea_resident" in w for w in option["warnings"]
    ), option["warnings"]
