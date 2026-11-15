from __future__ import annotations

import uuid
from datetime import date, timedelta
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
from app.modules.activities.models import Activity, ActivityRate
from app.modules.destinations.models import Destination
from app.modules.quotes.models import (
    Quote,
    QuoteOption,
    QuoteOptionLeg,
    QuoteVersion,
)
from app.modules.residence.models import ResidenceCategory
from app.modules.transport.models import TransferRate
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal

ARRIVAL, DEPARTURE = date(2026, 7, 1), date(2026, 7, 4)
MIDDLE = date(2026, 7, 2)
SEASON_FROM, SEASON_TO = date(2026, 1, 1), date(2026, 12, 31)

TWIN = D("18000")
CRUISE = "Sunset dhow cruise"
CRUISE_FARE = D("4000")
TRANSFER = D("3500")


@pytest_asyncio.fixture(loop_scope="session")
async def two_stop_trip():
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        fb = (
            await db.execute(select(MealPlan).where(MealPlan.code == "FB"))
        ).scalar_one()
        hb = (
            await db.execute(select(MealPlan).where(MealPlan.code == "HB"))
        ).scalar_one()
        citizen = (
            await db.execute(
                select(ResidenceCategory).where(ResidenceCategory.key == "citizen")
            )
        ).scalar_one()

        made: dict[str, str] = {}
        for key, label, plan in (
            ("city", "Programme City", hb),
            ("coast", "Programme Coast", fb),
        ):
            where = Destination(
                name=f"{label} {tag}",
                slug=f"{key}-programme-{tag}",
                type="city" if key == "city" else "beach",
            )
            db.add(where)
            await db.flush()
            hotel = Accommodation(
                name=f"{label} Hotel {tag}",
                slug=f"{key}-hotel-{tag}",
                destination_id=where.id,
                category="hotel",
            )
            db.add(hotel)
            await db.flush()
            room = RoomType(
                accommodation_id=hotel.id,
                name="Twin",
                code=f"{key[:3].upper()}TW",
                max_occupancy=2,
            )
            db.add(room)
            await db.flush()
            for occupancy, amount in ((2, TWIN), (1, TWIN * D("0.75"))):
                db.add(
                    AccommodationRate(
                        accommodation_id=hotel.id,
                        room_type_id=room.id,
                        meal_plan_id=plan.id,
                        residence_category_id=citizen.id,
                        season_name="standard",
                        occupancy=occupancy,
                        effective_from=SEASON_FROM,
                        effective_to=SEASON_TO,
                        currency="KES",
                        rate_per_night=amount,
                        rate_kind="sto",
                    )
                )
            db.add(
                TransferRate(
                    destination_id=where.id,
                    vehicle_type="saloon",
                    passenger_capacity=3,
                    route_label="Airport transfer",
                    price_per_leg=TRANSFER,
                    currency="KES",
                    effective_from=SEASON_FROM,
                    effective_to=SEASON_TO,
                )
            )
            made[f"{key}_destination"] = str(where.id)
            made[f"{key}_hotel"] = str(hotel.id)

        cruise = Activity(
            name=CRUISE,
            slug=f"programme-cruise-{tag}",
            destination_id=uuid.UUID(made["coast_destination"]),
            is_optional=False,
            is_mandatory=True,
        )
        db.add(cruise)
        await db.flush()
        db.add(
            ActivityRate(
                activity_id=cruise.id,
                residence_category_id=citizen.id,
                currency="KES",
                adult_price=CRUISE_FARE,
                child_price=CRUISE_FARE / 2,
                effective_from=SEASON_FROM,
                effective_to=SEASON_TO,
            )
        )
        await db.commit()
        ids = {
            **made,
            "cruise_id": str(cruise.id),
            "citizen": str(citizen.id),
            "meal_plan_fb": str(fb.id),
            "meal_plan_hb": str(hb.id),
        }

    yield ids

    async with AsyncSessionLocal() as db:
        mine = [uuid.UUID(ids["city_hotel"]), uuid.UUID(ids["coast_hotel"])]
        via_option = (
            (
                await db.execute(
                    select(QuoteOption.quote_id).where(
                        QuoteOption.accommodation_id.in_(mine)
                    )
                )
            )
            .scalars()
            .all()
        )
        via_leg = (
            (
                await db.execute(
                    select(QuoteOption.quote_id)
                    .join(
                        QuoteOptionLeg,
                        QuoteOptionLeg.quote_option_id == QuoteOption.id,
                    )
                    .where(QuoteOptionLeg.accommodation_id.in_(mine))
                )
            )
            .scalars()
            .all()
        )
        for quote_id in set(via_option) | set(via_leg):
            row = await db.get(Quote, quote_id)
            if row is not None:
                await db.delete(row)
        await db.flush()
        activity = await db.get(Activity, uuid.UUID(ids["cruise_id"]))
        if activity is not None:
            await db.delete(activity)
        for key in ("city_hotel", "coast_hotel"):
            row = await db.get(Accommodation, uuid.UUID(ids[key]))
            if row is not None:
                await db.delete(row)
        await db.flush()
        for key in ("city_destination", "coast_destination"):
            row = await db.get(Destination, uuid.UUID(ids[key]))
            if row is not None:
                await db.delete(row)
        await db.commit()


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _package(ids):
    return [
        {
            "sequence": 1,
            "destination_id": ids["city_destination"],
            "accommodation_id": ids["city_hotel"],
            "check_in": ARRIVAL.isoformat(),
            "check_out": MIDDLE.isoformat(),
            "requested_meal_plan_id": ids["meal_plan_hb"],
        },
        {
            "sequence": 2,
            "destination_id": ids["coast_destination"],
            "accommodation_id": ids["coast_hotel"],
            "check_in": MIDDLE.isoformat(),
            "check_out": DEPARTURE.isoformat(),
            "requested_meal_plan_id": ids["meal_plan_fb"],
        },
    ]


async def _create(
    client,
    h,
    ids,
    *,
    cruise_day=3,
    segments=None,
    departure=DEPARTURE,
    expect=201,
):
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Programme Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("programme"),
            "residence_category_id": ids["citizen"],
        },
    )
    assert record.status_code == 201, record.text
    body = {
        "client_id": record.json()["id"],
        "presentation_currency": "KES",
        "residence_category_id": ids["citizen"],
        "arrival_date": ARRIVAL.isoformat(),
        "departure_date": departure.isoformat(),
        "pax_count": 2,
        "requested_meal_plan_id": ids["meal_plan_fb"],
        "legs": [
            {
                "destination_id": ids["coast_destination"],
                "nights": 2,
                "activities": [{"activity_id": ids["cruise_id"], "day": cruise_day}],
            }
        ],
        "transport_segments": segments or [],
        "options": [
            {
                "accommodation_id": ids["city_hotel"],
                "is_recommended": True,
                "legs": _package(ids),
            }
        ],
    }
    created = await client.post(f"{API}/quotes", headers=h, json=body)
    assert created.status_code == expect, created.text
    return created


async def _issued(client, h, ids, **kwargs):
    quote = (await _create(client, h, ids, **kwargs)).json()
    priced = await client.post(
        f"{API}/quotes/{quote['id']}/options/price", headers=h
    )
    assert priced.status_code == 200, priced.text
    issued = await client.post(f"{API}/quotes/{quote['id']}/issue", headers=h)
    assert issued.status_code == 200, issued.text
    return quote, await _days(issued.json()["id"])


async def _days(version_id: str) -> list[dict]:
    async with AsyncSessionLocal() as db:
        version = await db.get(QuoteVersion, uuid.UUID(version_id))
        assert version is not None
        options = (version.snapshot or {}).get("options") or []
        assert options, version.snapshot
        return options[0]["days"]


async def test_the_programme_is_frozen_into_the_version(
    client, admin_tokens, two_stop_trip
):
    h = _h(admin_tokens)
    _, days = await _issued(client, h, two_stop_trip)
    assert [day["number"] for day in days] == [1, 2, 3, 4]
    assert [day["date"] for day in days] == [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-04",
    ]
    assert [day["has_night"] for day in days] == [True, True, True, False]
    assert days[0]["destination"].startswith("Programme City")
    assert days[1]["destination"].startswith("Programme Coast")
    assert days[0]["board"] == "HB"
    assert days[1]["board"] == "FB"
    assert days[-1]["board"] == ""
    assert days[-1]["is_departure"] is True


async def test_the_excursion_lands_on_the_day_it_was_scheduled_for(
    client, admin_tokens, two_stop_trip
):
    h = _h(admin_tokens)
    _, days = await _issued(client, h, two_stop_trip, cruise_day=3)
    assert days[2]["excursions"] == [CRUISE]
    assert all(not day["excursions"] for day in days if day["number"] != 3)


async def test_a_dated_transfer_lands_on_its_own_day(
    client, admin_tokens, two_stop_trip
):
    h = _h(admin_tokens)
    _, days = await _issued(
        client,
        h,
        two_stop_trip,
        segments=[
            {
                "sequence": 1,
                "kind": "transfer",
                "mode": "road",
                "vehicle_type": "saloon",
                "destination_id": two_stop_trip["city_destination"],
                "description": "Airport to hotel",
                "travel_date": ARRIVAL.isoformat(),
            },
            {
                "sequence": 2,
                "kind": "transfer",
                "mode": "road",
                "vehicle_type": "saloon",
                "destination_id": two_stop_trip["coast_destination"],
                "description": "Hotel to airport",
                "travel_date": DEPARTURE.isoformat(),
            },
        ],
    )
    assert days[0]["movements"] == [
        {"label": "Airport to hotel", "minutes": None}
    ]
    assert days[1]["movements"] == []
    assert days[-1]["movements"] == [
        {"label": "Hotel to airport", "minutes": None}
    ]


async def test_the_day_they_change_hotels_says_so(
    client, admin_tokens, two_stop_trip
):
    h = _h(admin_tokens)
    quote, days = await _issued(client, h, two_stop_trip)
    assert days[0]["moves_from"] == ""
    assert days[1]["moves_from"].startswith("Programme City Hotel")
    assert days[1]["property_name"].startswith("Programme Coast Hotel")

    page = await client.get(f"{API}/quotes/{quote['id']}/document.html", headers=h)
    assert page.status_code == 200, page.text
    assert "Programme City Hotel" in page.text
    assert "&#8594;" in page.text or "→" in page.text


async def test_the_rendered_document_prints_the_programme(
    client, admin_tokens, two_stop_trip
):
    h = _h(admin_tokens)
    quote, _ = await _issued(client, h, two_stop_trip)
    page = await client.get(f"{API}/quotes/{quote['id']}/document.html", headers=h)
    assert page.status_code == 200, page.text
    html = page.text

    assert "Your Itinerary" in html
    assert "Day 01" in html and "Day 04" in html
    assert "Wed 01 Jul" in html
    assert "Sat 04 Jul" in html
    assert CRUISE in html
    assert "Half-board meals" in html
    assert "Full-board meals" in html
    assert "Checkout" in html


async def test_a_beach_stay_with_nothing_happening_gets_no_programme_page(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Quiet Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("quiet"),
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
            "arrival_date": "2026-07-01",
            "departure_date": "2026-07-04",
            "pax_count": 2,
            "requested_meal_plan_id": ids["meal_plan_fb"],
            "options": [
                {
                    "accommodation_id": ids["acc_sto_full_board"],
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
    page = await client.get(f"{API}/quotes/{quote_id}/document.html", headers=h)
    assert page.status_code == 200, page.text
    assert "Your Itinerary" not in page.text
    assert len(await _days(issued.json()["id"])) == 4


async def test_an_excursion_off_the_trip_is_refused_at_creation(
    client, admin_tokens, two_stop_trip
):
    h = _h(admin_tokens)
    refused = await _create(client, h, two_stop_trip, cruise_day=9, expect=400)
    body = refused.json()
    assert "itinerary_activity_off_trip" in body["error"]["message"]
    assert "day 9" in body["error"]["message"]


async def test_a_transfer_dated_outside_the_trip_is_refused_at_creation(
    client, admin_tokens, two_stop_trip
):
    h = _h(admin_tokens)
    refused = await _create(
        client,
        h,
        two_stop_trip,
        segments=[
            {
                "sequence": 1,
                "kind": "transfer",
                "mode": "road",
                "vehicle_type": "saloon",
                "destination_id": two_stop_trip["city_destination"],
                "description": "Airport to hotel",
                "travel_date": (DEPARTURE + timedelta(days=30)).isoformat(),
            }
        ],
        expect=400,
    )
    assert "itinerary_movement_off_trip" in refused.json()["error"]["message"]


async def test_an_undated_transfer_is_an_advisory_at_readiness(
    client, admin_tokens, two_stop_trip
):
    h = _h(admin_tokens)
    quote = (
        await _create(
            client,
            h,
            two_stop_trip,
            segments=[
                {
                    "sequence": 1,
                    "kind": "transfer",
                    "mode": "road",
                    "vehicle_type": "saloon",
                    "destination_id": two_stop_trip["city_destination"],
                    "description": "Airport to hotel",
                }
            ],
        )
    ).json()
    readiness = await client.get(
        f"{API}/quotes/{quote['id']}/readiness", headers=h
    )
    assert readiness.status_code == 200, readiness.text
    body = readiness.json()
    undated = [
        p for p in body["problems"] if p["code"] == "itinerary_movement_undated"
    ]
    assert undated, body["problems"]
    assert undated[0]["severity"] == "advisory"
    assert body["is_ready"] is True
