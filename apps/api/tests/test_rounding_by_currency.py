from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.config import settings
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal

ARRIVAL, DEPARTURE = "2026-07-01", "2026-07-04"
USD_PER_PERSON, USD_GROUP = D("352"), D("704")
USD_KES = D("130")


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _quote(client, h, ids, *, currency, residence, cohorts=None, pax=2):
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Rounding Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("rounding"),
            "residence_category_id": ids[residence],
        },
    )
    assert record.status_code == 201, record.text
    body = {
        "client_id": record.json()["id"],
        "presentation_currency": currency,
        "residence_category_id": ids[residence],
        "arrival_date": ARRIVAL,
        "departure_date": DEPARTURE,
        "requested_meal_plan_id": ids["meal_plan_fb"],
        "options": [
            {"accommodation_id": ids["acc_sto_full_board"], "is_recommended": True}
        ],
    }
    if cohorts:
        body["cohorts"] = [
            {
                "residence_category_id": ids[residence_key],
                "traveller_type": kind,
                "headcount": n,
            }
            for residence_key, kind, n in cohorts
        ]
    else:
        body["pax_count"] = pax
    created = await client.post(f"{API}/quotes", headers=h, json=body)
    assert created.status_code == 201, created.text
    quote = created.json()
    priced = await client.post(
        f"{API}/quotes/{quote['id']}/options/price", headers=h
    )
    assert priced.status_code == 200, priced.text
    return quote, priced.json()["options"][0]


async def test_a_dollar_quote_rounds_to_the_next_dollar(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    _, option = await _quote(
        client, h, ids, currency="USD", residence="residence_non_resident"
    )
    assert D(option["per_person"]) == USD_PER_PERSON
    assert D(option["group_total"]) == USD_GROUP
    assert D(option["per_person"]) != D("400")


async def test_a_shilling_quote_still_rounds_to_the_next_hundred(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    _, option = await _quote(
        client, h, ids, currency="KES", residence="residence_citizen"
    )
    assert D(option["per_person"]) == D("17600")
    assert D(option["group_total"]) == D("35200")


async def test_each_cohort_rounds_in_the_currency_it_is_billed_in(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    _, option = await _quote(
        client,
        h,
        ids,
        currency="KES",
        residence="residence_citizen",
        cohorts=[
            ("residence_citizen", "adult", 2),
            ("residence_non_resident", "adult", 2),
        ],
    )
    by_residence = {row["residence"]: row for row in option["cohorts"]}
    assert set(by_residence) == {"citizen", "non_resident"}

    citizen = by_residence["citizen"]
    assert citizen["currency"] == "KES"
    assert D(citizen["per_person"]) == D("17600")

    visitor = by_residence["non_resident"]
    assert visitor["currency"] == "USD"
    assert D(visitor["per_person"]) == USD_PER_PERSON
    assert D(visitor["total"]) == USD_GROUP

    assert D(citizen["total"]) == D(citizen["per_person"]) * D(2)
    assert D(visitor["total"]) == D(visitor["per_person"]) * D(2)


async def test_the_step_is_configurable_and_falls_back(
    client, admin_tokens, sample_catalogue, restore_pricing_config
):
    h, ids = _h(admin_tokens), sample_catalogue
    config = (await client.get(f"{API}/pricing-config", headers=h)).json()
    assert config["per_person_rounding_by_currency"] == {
        "USD": "1",
        "EUR": "1",
        "GBP": "1",
    }, config["per_person_rounding_by_currency"]

    emptied = await client.patch(
        f"{API}/pricing-config",
        headers=h,
        json={"per_person_rounding_by_currency": {}},
    )
    assert emptied.status_code == 200, emptied.text
    _, option = await _quote(
        client, h, ids, currency="USD", residence="residence_non_resident"
    )
    assert D(option["per_person"]) == D("400"), "the fallback is not being used"

    restored = await client.patch(
        f"{API}/pricing-config",
        headers=h,
        json={"per_person_rounding_by_currency": {"USD": "5"}},
    )
    assert restored.status_code == 200, restored.text
    _, option = await _quote(
        client, h, ids, currency="USD", residence="residence_non_resident"
    )
    assert D(option["per_person"]) == D("355")
