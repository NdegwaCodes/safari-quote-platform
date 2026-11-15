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
from app.modules.quotes.models import Quote, QuoteOption
from app.modules.residence.models import ResidenceCategory
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal

ARRIVAL, DEPARTURE = "2026-07-01", "2026-07-04"
CROSSING_ARRIVAL, CROSSING_DEPARTURE = "2026-07-30", "2026-08-02"

STATED_FROM, STATED_TO = date(2026, 1, 1), date(2026, 7, 31)
SILENT_FROM, SILENT_TO = date(2026, 8, 1), date(2026, 12, 31)

NIGHTS = 3
KES_TWIN, KES_SINGLE, KES_CHILD = D("20000"), D("15000"), D("5000")
USD_TWIN, USD_SINGLE, USD_CHILD = D("300"), D("225"), D("50")

CONTINGENCY, PROFIT = D("1.05"), D("1.24")


def _up(amount: Decimal, step: Decimal) -> Decimal:
    return (amount / step).to_integral_value(rounding="ROUND_CEILING") * step


@pytest_asyncio.fixture(loop_scope="session")
async def family_resort():
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        fb = (
            await db.execute(select(MealPlan).where(MealPlan.code == "FB"))
        ).scalar_one()
        bb = (
            await db.execute(select(MealPlan).where(MealPlan.code == "BB"))
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

        beach = Destination(
            name=f"Child Rate Bay {tag}", slug=f"child-rate-bay-{tag}", type="beach"
        )
        db.add(beach)
        await db.flush()
        resort = Accommodation(
            name=f"Family Resort {tag}",
            slug=f"family-resort-{tag}",
            destination_id=beach.id,
            category="resort",
        )
        db.add(resort)
        await db.flush()
        twin = RoomType(
            accommodation_id=resort.id, name="Family Twin", code="FTW", max_occupancy=2
        )
        db.add(twin)
        await db.flush()

        for rc, currency, double, single, child in (
            (citizen, "KES", KES_TWIN, KES_SINGLE, KES_CHILD),
            (visitor, "USD", USD_TWIN, USD_SINGLE, USD_CHILD),
        ):
            for occupancy, amount in ((2, double), (1, single)):
                db.add(
                    AccommodationRate(
                        accommodation_id=resort.id,
                        room_type_id=twin.id,
                        meal_plan_id=fb.id,
                        residence_category_id=rc.id,
                        season_name="stated",
                        occupancy=occupancy,
                        effective_from=STATED_FROM,
                        effective_to=STATED_TO,
                        currency=currency,
                        rate_per_night=amount,
                        child_rate=child,
                        rate_kind="sto",
                    )
                )
                db.add(
                    AccommodationRate(
                        accommodation_id=resort.id,
                        room_type_id=twin.id,
                        meal_plan_id=fb.id,
                        residence_category_id=rc.id,
                        season_name="silent",
                        occupancy=occupancy,
                        effective_from=SILENT_FROM,
                        effective_to=SILENT_TO,
                        currency=currency,
                        rate_per_night=amount,
                        rate_kind="sto",
                    )
                )
                db.add(
                    AccommodationRate(
                        accommodation_id=resort.id,
                        room_type_id=twin.id,
                        meal_plan_id=bb.id,
                        residence_category_id=rc.id,
                        season_name="stated",
                        occupancy=occupancy,
                        effective_from=STATED_FROM,
                        effective_to=SILENT_TO,
                        currency=currency,
                        rate_per_night=amount - (amount / 4),
                        rate_kind="sto",
                    )
                )
        await db.commit()
        ids = {
            "destination_id": str(beach.id),
            "accommodation_id": str(resort.id),
            "citizen": str(citizen.id),
            "non_resident": str(visitor.id),
            "meal_plan_fb": str(fb.id),
            "meal_plan_bb": str(bb.id),
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
        resort_row = await db.get(Accommodation, uuid.UUID(ids["accommodation_id"]))
        if resort_row is not None:
            await db.delete(resort_row)
            await db.flush()
        beach_row = await db.get(Destination, uuid.UUID(ids["destination_id"]))
        if beach_row is not None:
            await db.delete(beach_row)
        await db.commit()


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _priced(
    client,
    h,
    resort,
    *,
    cohorts,
    plan="meal_plan_fb",
    arrival=ARRIVAL,
    departure=DEPARTURE,
    currency="KES",
):
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Family Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("childrate"),
            "residence_category_id": resort["citizen"],
        },
    )
    assert record.status_code == 201, record.text
    quote = await client.post(
        f"{API}/quotes",
        headers=h,
        json={
            "client_id": record.json()["id"],
            "presentation_currency": currency,
            "residence_category_id": resort["citizen"],
            "arrival_date": arrival,
            "departure_date": departure,
            "requested_meal_plan_id": resort[plan],
            "cohorts": [
                {
                    "residence_category_id": resort[residence],
                    "traveller_type": kind,
                    "headcount": n,
                }
                for residence, kind, n in cohorts
            ],
            "options": [{"accommodation_id": resort["accommodation_id"]}],
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


def _by_cohort(option):
    return {
        f"{row['residence']}:{row['traveller_type']}": row
        for row in option["cohorts"]
    }


async def test_a_child_sharing_is_charged_the_sheets_child_rate(
    client, admin_tokens, family_resort
):
    option = await _priced(
        client,
        _h(admin_tokens),
        family_resort,
        cohorts=[("citizen", "adult", 2), ("citizen", "child", 2)],
    )
    components = option["build_up"]["components"]
    assert D(components["accommodation"]) == KES_TWIN * NIGHTS + KES_CHILD * 2 * NIGHTS
    assert D(components["accommodation"]) == D("90000")


async def test_the_children_do_not_add_a_room(client, admin_tokens, family_resort):
    option = await _priced(
        client,
        _h(admin_tokens),
        family_resort,
        cohorts=[("citizen", "adult", 2), ("citizen", "child", 2)],
    )
    assert option["rooms_required"] == 1


async def test_the_child_bears_its_own_bed_and_not_a_share_of_the_room(
    client, admin_tokens, family_resort
):
    option = await _priced(
        client,
        _h(admin_tokens),
        family_resort,
        cohorts=[("citizen", "adult", 2), ("citizen", "child", 2)],
    )
    rows = _by_cohort(option)
    adult, child = rows["citizen:adult"], rows["citizen:child"]

    assert D(adult["per_person"]) == _up(
        KES_TWIN * NIGHTS * CONTINGENCY * PROFIT / 2, D("100")
    )
    assert D(adult["per_person"]) == D("39100")
    assert D(child["per_person"]) == _up(
        KES_CHILD * 2 * NIGHTS * CONTINGENCY * PROFIT / 2, D("100")
    )
    assert D(child["per_person"]) == D("19600")
    assert D(option["group_total"]) == D(adult["total"]) + D(child["total"])


async def test_a_sheet_that_states_no_child_rate_charges_a_child_as_an_adult(
    client, admin_tokens, family_resort
):
    option = await _priced(
        client,
        _h(admin_tokens),
        family_resort,
        cohorts=[("citizen", "adult", 2), ("citizen", "child", 2)],
        plan="meal_plan_bb",
    )
    assert option["rooms_required"] == 2
    assert D(option["build_up"]["components"]["accommodation"]) == D("90000")
    rows = _by_cohort(option)
    assert (
        D(rows["citizen:adult"]["per_person"])
        == D(rows["citizen:child"]["per_person"])
    )


async def test_a_child_rate_missing_for_part_of_the_stay_is_not_used_at_all(
    client, admin_tokens, family_resort
):
    option = await _priced(
        client,
        _h(admin_tokens),
        family_resort,
        cohorts=[("citizen", "adult", 2), ("citizen", "child", 2)],
        arrival=CROSSING_ARRIVAL,
        departure=CROSSING_DEPARTURE,
    )
    assert option["rooms_required"] == 2
    assert D(option["build_up"]["components"]["accommodation"]) == KES_TWIN * 2 * NIGHTS
    rows = _by_cohort(option)
    assert (
        D(rows["citizen:adult"]["per_person"])
        == D(rows["citizen:child"]["per_person"])
    )


async def test_each_residency_charges_its_children_off_its_own_sheet(
    client, admin_tokens, family_resort
):
    option = await _priced(
        client,
        _h(admin_tokens),
        family_resort,
        cohorts=[
            ("citizen", "adult", 2),
            ("citizen", "child", 1),
            ("non_resident", "adult", 2),
            ("non_resident", "child", 1),
        ],
    )
    rows = _by_cohort(option)
    assert set(rows) == {
        "citizen:adult",
        "citizen:child",
        "non_resident:adult",
        "non_resident:child",
    }

    assert rows["citizen:adult"]["currency"] == "KES"
    assert D(rows["citizen:adult"]["per_person"]) == D("39100")
    assert D(rows["citizen:child"]["per_person"]) == D("19600")

    assert rows["non_resident:adult"]["currency"] == "USD"
    assert D(rows["non_resident:adult"]["per_person"]) == D("586")
    assert D(rows["non_resident:child"]["per_person"]) == D("196")

    assert option["rooms_required"] == 2


async def test_children_only_are_room_occupants(
    client, admin_tokens, family_resort
):
    option = await _priced(
        client,
        _h(admin_tokens),
        family_resort,
        cohorts=[("citizen", "child", 2)],
    )
    assert option["rooms_required"] == 1
    assert D(option["build_up"]["components"]["accommodation"]) == KES_TWIN * NIGHTS


async def test_the_worksheet_states_both_bases(
    client, admin_tokens, family_resort
):
    h = _h(admin_tokens)
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Worksheet Family {uuid.uuid4().hex[:8]}",
            "email": unique_email("childsheet"),
            "residence_category_id": family_resort["citizen"],
        },
    )
    quote = await client.post(
        f"{API}/quotes",
        headers=h,
        json={
            "client_id": record.json()["id"],
            "presentation_currency": "KES",
            "residence_category_id": family_resort["citizen"],
            "arrival_date": ARRIVAL,
            "departure_date": DEPARTURE,
            "requested_meal_plan_id": family_resort["meal_plan_fb"],
            "cohorts": [
                {
                    "residence_category_id": family_resort["citizen"],
                    "traveller_type": kind,
                    "headcount": n,
                }
                for kind, n in (("adult", 2), ("child", 2))
            ],
            "options": [
                {
                    "accommodation_id": family_resort["accommodation_id"],
                    "is_recommended": True,
                }
            ],
        },
    )
    assert quote.status_code == 201, quote.text
    quote_id = quote.json()["id"]
    priced = await client.post(f"{API}/quotes/{quote_id}/options/price", headers=h)
    assert priced.status_code == 200, priced.text
    issued = await client.post(f"{API}/quotes/{quote_id}/issue", headers=h)
    assert issued.status_code == 200, issued.text

    sheet = await client.get(f"{API}/quotes/{quote_id}/worksheet.html", headers=h)
    assert sheet.status_code == 200, sheet.text
    html = sheet.text
    assert "child sharing (citizen)" in html
    assert "per_room_per_night" in html
    assert "per_person_per_night" in html
    assert "KES 30,000" in html
    assert "KES 60,000" in html
