from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.modules.quotes.models import Quote
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal
ARRIVAL, DEPARTURE = "2026-07-01", "2026-07-04"
SWITCH = "2026-07-02"


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _record(client, h, residence_category_id):
    resp = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Package Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("package"),
            "residence_category_id": residence_category_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _quote(client, h, ids, *, options, arrival=ARRIVAL, departure=DEPARTURE):
    record = await _record(client, h, ids["residence_citizen"])
    return await client.post(
        f"{API}/quotes",
        headers=h,
        json={
            "client_id": record["id"],
            "presentation_currency": "KES",
            "residence_category_id": ids["residence_citizen"],
            "arrival_date": arrival,
            "departure_date": departure,
            "pax_count": 2,
            "requested_meal_plan_id": ids["meal_plan_fb"],
            "options": options,
        },
    )


def _two_legs(ids, lodge, *, switch=SWITCH, departure=DEPARTURE, plan=None):
    first = {
        "sequence": 1,
        "destination_id": ids["destination_diani"],
        "accommodation_id": ids["acc_sto_full_board"],
        "check_in": ARRIVAL,
        "check_out": switch,
    }
    second = {
        "sequence": 2,
        "destination_id": lodge["destination_id"],
        "accommodation_id": lodge["accommodation_id"],
        "check_in": switch,
        "check_out": departure,
    }
    if plan:
        second["requested_meal_plan_id"] = plan
    return {
        "accommodation_id": ids["acc_sto_full_board"],
        "sort_order": 1,
        "legs": [first, second],
    }


async def _price(client, h, quote_id):
    resp = await client.post(f"{API}/quotes/{quote_id}/options/price", headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_a_two_destination_package_prices_both_legs(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(
        client, h, ids, options=[_two_legs(ids, upcountry_lodge)]
    )
    assert quote.status_code == 201, quote.text
    result = await _price(client, h, quote.json()["id"])

    assert len(result["options"]) == 1
    option = result["options"][0]
    assert D(option["build_up"]["components"]["accommodation"]) == D("45000")
    assert D(option["per_person"]) == D("29300")
    assert D(option["group_total"]) == D("58600")
    assert option["nights"] == 3


async def test_each_leg_reports_its_own_property_room_and_nights(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(client, h, ids, options=[_two_legs(ids, upcountry_lodge)])
    option = (await _price(client, h, quote.json()["id"]))["options"][0]

    legs = option["legs"]
    assert [one["sequence"] for one in legs] == [1, 2]
    assert [one["nights"] for one in legs] == [1, 2]
    assert "Coral Shoals" in legs[0]["accommodation_name"]
    assert "Highland Lodge" in legs[1]["accommodation_name"]
    assert legs[0]["room_type_name"] != legs[1]["room_type_name"]
    assert option["rooms_required"] == 1


async def test_the_option_name_shows_the_whole_itinerary(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(client, h, ids, options=[_two_legs(ids, upcountry_lodge)])
    option = (await _price(client, h, quote.json()["id"]))["options"][0]
    assert "→" in option["accommodation_name"]
    assert "Coral Shoals" in option["accommodation_name"]
    assert "Highland Lodge" in option["accommodation_name"]


async def test_a_meal_plan_is_chosen_per_leg(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(
        client,
        h,
        ids,
        options=[
            _two_legs(ids, upcountry_lodge, plan=upcountry_lodge["meal_plan_bb"])
        ],
    )
    option = (await _price(client, h, quote.json()["id"]))["options"][0]

    assert D(option["build_up"]["components"]["accommodation"]) == D("37000")
    legs = option["legs"]
    assert legs[0]["meal_plan_code"] == "FB"
    assert legs[1]["meal_plan_code"] == "BB"
    assert legs[1]["meal_plan_fallback_from"] is None


async def test_the_resolution_is_written_back_per_leg(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(client, h, ids, options=[_two_legs(ids, upcountry_lodge)])
    quote_id = quote.json()["id"]
    await _price(client, h, quote_id)

    fresh = await client.get(f"{API}/quotes/{quote_id}", headers=h)
    legs = fresh.json()["options"][0]["legs"]
    assert len(legs) == 2
    for leg in legs:
        assert leg["room_type_id"] is not None
        assert leg["meal_plan_id"] is not None
        assert leg["rooms_required"] == 1
    assert legs[0]["room_type_id"] != legs[1]["room_type_id"]


async def test_a_single_property_option_is_a_package_of_one(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(
        client,
        h,
        ids,
        options=[{"accommodation_id": ids["acc_sto_full_board"]}],
    )
    option = (await _price(client, h, quote.json()["id"]))["options"][0]
    assert len(option["legs"]) == 1
    assert option["legs"][0]["nights"] == 3
    assert option["accommodation_name"].startswith("Coral Shoals Resort")
    assert "→" not in option["accommodation_name"]


async def test_a_package_with_a_missing_night_is_refused_at_creation(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    option = _two_legs(ids, upcountry_lodge)
    option["legs"][1]["check_in"] = "2026-07-03"
    resp = await _quote(client, h, ids, options=[option])
    assert resp.status_code == 400, resp.text
    assert "package_leg_gap" in resp.text


async def test_a_package_that_does_not_reach_departure_is_refused(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    option = _two_legs(ids, upcountry_lodge, departure="2026-07-03")
    resp = await _quote(client, h, ids, options=[option])
    assert resp.status_code == 400, resp.text
    assert "package_ends_before_departure" in resp.text


async def test_the_same_package_cannot_be_offered_twice(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    first = _two_legs(ids, upcountry_lodge)
    second = dict(_two_legs(ids, upcountry_lodge), sort_order=2)
    resp = await _quote(client, h, ids, options=[first, second])
    assert resp.status_code == 400, resp.text
    assert "repeats a package" in resp.text


async def test_two_packages_may_share_a_property(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    shared = _two_legs(ids, upcountry_lodge)
    other = _two_legs(ids, upcountry_lodge, switch="2026-07-03")
    other["sort_order"] = 2
    resp = await _quote(client, h, ids, options=[shared, other])
    assert resp.status_code == 201, resp.text
    assert len(resp.json()["options"]) == 2


async def test_a_leg_that_cannot_be_priced_drops_the_whole_package(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    option = _two_legs(ids, upcountry_lodge)
    option["legs"][1]["accommodation_id"] = upcountry_lodge["rateless_id"]
    resp = await _quote(client, h, ids, options=[option])
    assert resp.status_code == 201, resp.text
    result = await _price(client, h, resp.json()["id"])
    assert result["options"] == []
    joined = " ".join(result["warnings"])
    assert "leg 2" in joined, joined


async def test_readiness_catches_a_package_broken_by_a_date_change(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(client, h, ids, options=[_two_legs(ids, upcountry_lodge)])
    quote_id = quote.json()["id"]

    ready = await client.get(f"{API}/quotes/{quote_id}/readiness", headers=h)
    assert not any(
        p["code"].startswith("package_") for p in ready.json()["problems"]
    ), ready.json()["problems"]

    async with AsyncSessionLocal() as db:
        row = await db.get(Quote, uuid.UUID(quote_id))
        row.departure_date = date(2026, 7, 5)
        await db.commit()

    ready = await client.get(f"{API}/quotes/{quote_id}/readiness", headers=h)
    body = ready.json()
    codes = {p["code"] for p in body["problems"]}
    assert "package_ends_before_departure" in codes, body["problems"]
    assert body["is_ready"] is False


async def test_issuing_takes_the_headline_from_the_recommended_package(
    client, admin_tokens, sample_catalogue, upcountry_lodge
):
    h, ids = _h(admin_tokens), sample_catalogue
    recommended = _two_legs(ids, upcountry_lodge)
    recommended["is_recommended"] = True
    later_switch = _two_legs(ids, upcountry_lodge, switch="2026-07-03")
    later_switch["sort_order"] = 2
    quote = await _quote(client, h, ids, options=[recommended, later_switch])
    assert quote.status_code == 201, quote.text
    quote_id = quote.json()["id"]

    issued = await client.post(f"{API}/quotes/{quote_id}/issue", headers=h)
    assert issued.status_code == 200, issued.text
    version = issued.json()
    assert D(version["selling_price"]) == D("58600.00")

    rows = version["options"]
    assert len(rows) == 2, rows
    assert len({row["option_id"] for row in rows}) == 2, rows
    by_recommendation = {row["is_recommended"]: D(row["selling_total"]) for row in rows}
    assert by_recommendation == {True: D("58600.00"), False: D("47000.00")}
    stored = (await client.get(f"{API}/quotes/{quote_id}", headers=h)).json()
    assert {row["option_id"] for row in rows} == {o["id"] for o in stored["options"]}
