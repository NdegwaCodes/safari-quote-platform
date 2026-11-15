from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.core.config import settings
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")


def D(value: str) -> Decimal:
    return Decimal(value)


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _client_record(client, h, residence_category_id):
    resp = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Option Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("options"),
            "residence_category_id": residence_category_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _quote(
    client,
    h,
    ids,
    *,
    accommodations,
    arrival="2026-07-01",
    departure="2026-07-04",
    pax=25,
    residence="residence_citizen",
    currency="KES",
    plan="meal_plan_fb",
    travellers=None,
    **option_overrides,
):
    record = await _client_record(client, h, ids[residence])
    body = {
        "client_id": record["id"],
        "presentation_currency": currency,
        "residence_category_id": ids[residence],
        "arrival_date": arrival,
        "departure_date": departure,
        "pax_count": pax,
        "requested_meal_plan_id": ids[plan],
        "travellers": travellers or [],
        "options": [
            {"accommodation_id": ids[key], "sort_order": order, **option_overrides}
            for order, key in enumerate(accommodations, start=1)
        ],
    }
    resp = await client.post(f"{API}/quotes", headers=h, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _price(client, h, quote_id):
    resp = await client.post(f"{API}/quotes/{quote_id}/options/price", headers=h)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _option(result, name_fragment):
    matches = [
        o for o in result["options"] if name_fragment in o["accommodation_name"]
    ]
    priced = [o["accommodation_name"] for o in result["options"]]
    assert len(matches) == 1, f"{name_fragment} not uniquely priced; got {priced}"
    return matches[0]


async def _agent_headers(client, h):
    email = unique_email("optagent")
    await client.post(
        f"{API}/users",
        headers=h,
        json={"email": email, "password": "AgentPass123", "role_keys": ["sales_agent"]},
    )
    login = await client.post(
        f"{API}/auth/login", data={"username": email, "password": "AgentPass123"}
    )
    assert login.status_code == 200, login.text
    return _h(login.json())


async def test_prices_the_cheapest_room_type_using_per_occupancy_rates(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(client, h, sample_catalogue, accommodations=["acc_sto_full_board"])
    result = await _price(client, h, quote["id"])

    option = _option(result, "Coral Shoals")
    assert option["room_type_name"] == "Twin"
    assert option["rooms_required"] == 13
    assert option["nights"] == 3
    assert option["meal_plan_code"] == "FB"
    assert D(option["build_up"]["components"]["accommodation"]) == D("343500")
    assert D(option["build_up"]["cost_subtotal"]) == D("343500")
    assert D(option["build_up"]["contingency_value"]) == D("17175")
    assert D(option["build_up"]["cost_basis"]) == D("360675")
    assert D(option["build_up"]["profit_value"]) == D("86562")
    assert D(option["per_person"]) == D("17900")
    assert D(option["group_total"]) == D("447500")


async def test_per_person_times_pax_equals_the_group_total(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    for pax in (1, 2, 7, 13, 25):
        quote = await _quote(
            client, h, sample_catalogue, accommodations=["acc_sto_full_board"], pax=pax
        )
        option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
        assert D(option["per_person"]) * pax == D(option["group_total"]), pax


async def test_a_lone_guest_pays_the_quoted_single_rate(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client, h, sample_catalogue, accommodations=["acc_sto_full_board"], pax=1
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
    assert option["rooms_required"] == 1
    assert D(option["build_up"]["components"]["accommodation"]) == D("19500")


async def test_rack_discount_passes_half_to_the_client_and_keeps_half(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(client, h, sample_catalogue, accommodations=["acc_rack_discounted"])
    option = _option(await _price(client, h, quote["id"]), "Mvule")

    assert D(option["build_up"]["components"]["accommodation"]) == D("865800")
    assert D(option["supplier_paid_total"]) == D("795600")
    assert D(option["retained_discount"]) == D("70200")
    assert D(option["build_up"]["profit_value"]) == D("218181.6")


async def test_a_stated_single_supplement_is_surfaced_not_added(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(client, h, sample_catalogue, accommodations=["acc_rack_discounted"])
    option = _option(await _price(client, h, quote["id"]), "Mvule")

    assert D(option["build_up"]["components"]["accommodation"]) == D("865800")
    joined = " ".join(option["warnings"])
    assert "single supplement" in joined
    assert "charged in full" in joined
    assert "per person sharing" in joined


async def test_an_sto_rate_is_used_as_is(client, admin_tokens, sample_catalogue):
    h = _h(admin_tokens)
    quote = await _quote(client, h, sample_catalogue, accommodations=["acc_sto_full_board"])
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
    assert D(option["supplier_paid_total"]) == D("343500")
    assert D(option["retained_discount"]) == D("0")


async def test_a_short_festive_stay_is_refused_but_still_shown(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_min_stay"],
        arrival="2026-12-21",
        departure="2026-12-24",
    )
    result = await _price(client, h, quote["id"])

    assert result["options"] == []
    assert len(result["rejected"]) == 1
    refused = result["rejected"][0]
    assert refused["accommodation_id"] == sample_catalogue["acc_min_stay"]
    assert refused["reason"] == (
        "Requires a minimum stay of 4 nights; this itinerary is 3 nights."
    )


async def test_the_refusal_reason_says_nothing_commercial(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_min_stay"],
        arrival="2026-12-21",
        departure="2026-12-24",
    )
    reason = (await _price(client, h, quote["id"]))["rejected"][0]["reason"].lower()
    for forbidden in ("cost", "margin", "profit", "supplier", "rate", "discount"):
        assert forbidden not in reason, forbidden


async def test_the_same_property_prices_normally_outside_the_restricted_window(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(client, h, sample_catalogue, accommodations=["acc_min_stay"])
    result = await _price(client, h, quote["id"])

    assert result["rejected"] == []
    option = _option(result, "Chui")
    assert D(option["build_up"]["components"]["accommodation"]) == D("546000")


async def test_a_long_enough_festive_stay_gets_the_festive_rate(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_min_stay"],
        arrival="2026-12-21",
        departure="2026-12-25",
        pax=2,
    )
    option = _option(await _price(client, h, quote["id"]), "Chui")
    assert D(option["build_up"]["components"]["accommodation"]) == D("88000")


async def test_a_mandatory_supplement_is_charged_only_for_the_nights_it_covers(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_sto_full_board"],
        arrival="2026-12-23",
        departure="2026-12-27",
        pax=2,
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")

    assert len(option["supplements"]) == 1
    supplement = option["supplements"][0]
    assert supplement["kind"] == "gala"
    assert supplement["basis"] == "per_person_per_night"
    assert supplement["nights"] == 2
    assert D(supplement["cost"]) == D("10000")

    assert D(option["build_up"]["components"]["accommodation"]) == D("36000")
    assert D(option["build_up"]["components"]["supplements"]) == D("10000")
    assert D(option["build_up"]["cost_subtotal"]) == D("46000")
    assert D(option["per_person"]) == D("30000")
    assert D(option["group_total"]) == D("60000")


async def test_no_supplement_outside_its_window(client, admin_tokens, sample_catalogue):
    h = _h(admin_tokens)
    quote = await _quote(client, h, sample_catalogue, accommodations=["acc_sto_full_board"])
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
    assert option["supplements"] == []
    assert "supplements" not in option["build_up"]["components"]


async def test_full_board_request_falls_back_to_bed_and_breakfast(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_bb_only"],
        chef_fee_per_meal="5000",
        manual_meal_cost="30000",
    )
    option = _option(await _price(client, h, quote["id"]), "Upepo")

    assert option["meal_plan_code"] == "BB"
    assert option["meal_plan_fallback_from"] == "FB"
    assert option["is_comparable"] is False
    assert D(option["build_up"]["components"]["chef"]) == D("30000")
    assert D(option["build_up"]["components"]["meals"]) == D("30000")
    assert D(option["build_up"]["cost_subtotal"]) == D("294000")
    assert D(option["per_person"]) == D("15400")
    assert D(option["group_total"]) == D("385000")


async def test_the_chef_fee_defaults_when_the_agent_has_not_typed_one(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_bb_only"],
        manual_meal_cost="30000",
    )
    option = _option(await _price(client, h, quote["id"]), "Upepo")

    assert D(option["build_up"]["components"]["chef"]) == D("225000")
    assert D(option["build_up"]["components"]["meals"]) == D("30000")
    assert D(option["build_up"]["cost_subtotal"]) == D("489000")
    assert D(option["per_person"]) == D("25500")
    assert D(option["group_total"]) == D("637500")


async def test_an_agents_own_chef_fee_overrides_the_default(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_bb_only"],
        chef_fee_per_meal="1",
        manual_meal_cost="30000",
    )
    option = _option(await _price(client, h, quote["id"]), "Upepo")
    assert D(option["build_up"]["components"]["chef"]) == D("6")


async def test_a_bed_and_breakfast_option_without_a_chef_is_flagged(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(client, h, sample_catalogue, accommodations=["acc_bb_only"])
    option = _option(await _price(client, h, quote["id"]), "Upepo")
    joined = " ".join(option["warnings"])
    assert "needs a chef" in joined
    assert "6 group meal(s)" in joined


async def test_no_chef_on_a_full_board_option(client, admin_tokens, sample_catalogue):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_sto_full_board"],
        chef_fee_per_meal="5000",
        manual_meal_cost="30000",
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
    assert "chef" not in option["build_up"]["components"]
    assert "meals" not in option["build_up"]["components"]


async def test_the_agent_cover_fee_reaches_the_client_unmarked_up(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    plain = await _quote(client, h, sample_catalogue, accommodations=["acc_sto_full_board"])
    with_fee = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_sto_full_board"],
        agent_cover_fee="25000",
    )
    base = _option(await _price(client, h, plain["id"]), "Coral Shoals")
    loaded = _option(await _price(client, h, with_fee["id"]), "Coral Shoals")

    assert D(loaded["build_up"]["profit_value"]) == D(base["build_up"]["profit_value"])
    assert D(loaded["build_up"]["selling_total"]) - D(
        base["build_up"]["selling_total"]
    ) == D("25000")
    assert D(loaded["build_up"]["agent_cover_fee"]) == D("25000")


async def test_a_mixed_group_is_quoted_as_a_total_only(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_sto_full_board"],
        pax=2,
        travellers=[{"traveller_type": "adult"}, {"traveller_type": "child", "age": 8}],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
    assert option["per_person"] is None
    assert D(option["group_total"]) > 0


async def test_per_quote_overrides_beat_the_business_defaults(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    record = await _client_record(client, h, sample_catalogue["residence_citizen"])
    resp = await client.post(
        f"{API}/quotes",
        headers=h,
        json={
            "client_id": record["id"],
            "presentation_currency": "KES",
            "residence_category_id": sample_catalogue["residence_citizen"],
            "arrival_date": "2026-07-01",
            "departure_date": "2026-07-04",
            "pax_count": 25,
            "requested_meal_plan_id": sample_catalogue["meal_plan_fb"],
            "profit_pct": "10",
            "contingency_pct": "0",
            "options": [
                {"accommodation_id": sample_catalogue["acc_sto_full_board"]}
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    option = _option(await _price(client, h, resp.json()["id"]), "Coral Shoals")
    assert D(option["build_up"]["contingency_value"]) == D("0")
    assert D(option["build_up"]["cost_basis"]) == D("343500")
    assert D(option["build_up"]["profit_value"]) == D("34350")


async def test_a_usd_rate_converts_at_the_contract_rate(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_sto_full_board"],
        pax=2,
        residence="residence_non_resident",
        currency="KES",
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
    assert D(option["build_up"]["components"]["accommodation"]) == D("70200")


async def test_resident_and_non_resident_prices_differ_materially(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    resident = await _quote(
        client, h, sample_catalogue, accommodations=["acc_sto_full_board"], pax=2
    )
    visitor = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_sto_full_board"],
        pax=2,
        residence="residence_non_resident",
        currency="KES",
    )
    local = _option(await _price(client, h, resident["id"]), "Coral Shoals")
    foreign = _option(await _price(client, h, visitor["id"]), "Coral Shoals")
    assert D(local["build_up"]["components"]["accommodation"]) == D("27000")
    assert D(foreign["build_up"]["components"]["accommodation"]) == D("70200")


async def test_pricing_writes_the_resolution_back_onto_the_quote(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_sto_full_board", "acc_bb_only"],
    )
    assert all(o["room_type_id"] is None for o in quote["options"])

    await _price(client, h, quote["id"])
    reloaded = (await client.get(f"{API}/quotes/{quote['id']}", headers=h)).json()

    coral = next(
        o
        for o in reloaded["options"]
        if o["accommodation_id"] == sample_catalogue["acc_sto_full_board"]
    )
    assert coral["room_type_id"] == sample_catalogue["room_coral_twin"]
    assert coral["meal_plan_id"] == sample_catalogue["meal_plan_fb"]
    assert coral["rooms_required"] == 13
    assert coral["meal_plan_fallback_from"] is None

    upepo = next(
        o
        for o in reloaded["options"]
        if o["accommodation_id"] == sample_catalogue["acc_bb_only"]
    )
    assert upepo["meal_plan_id"] == sample_catalogue["meal_plan_bb"]
    assert upepo["meal_plan_fallback_from"] == "FB"
    assert upepo["is_comparable"] is False


async def test_repricing_replaces_refusals_rather_than_accumulating_them(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_min_stay"],
        arrival="2026-12-21",
        departure="2026-12-24",
    )
    first = await _price(client, h, quote["id"])
    second = await _price(client, h, quote["id"])
    assert len(first["rejected"]) == 1
    assert len(second["rejected"]) == 1

    stored = (await client.get(f"{API}/quotes/{quote['id']}", headers=h)).json()
    assert len(stored["rejected_candidates"]) == 1


async def test_options_are_priced_in_the_agents_order(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_bb_only", "acc_rack_discounted", "acc_sto_full_board"],
    )
    result = await _price(client, h, quote["id"])
    assert [o["accommodation_name"] for o in result["options"]] == [
        "Upepo Guest House (demo)",
        "Mvule Beach Lodge (demo)",
        "Coral Shoals Resort (demo)",
    ]


COST_KEYS = {
    "cost_subtotal",
    "cost_basis",
    "contingency_value",
    "profit_value",
    "after_profit",
    "agent_cover_fee",
    "supplier_paid_total",
    "retained_discount",
    "build_up",
    "components",
    "supplements",
    "warnings",
    "meal_plan_fallback_from",
}


def _keys_everywhere(payload) -> set[str]:
    found: set[str] = set()
    if isinstance(payload, dict):
        found |= set(payload)
        for value in payload.values():
            found |= _keys_everywhere(value)
    elif isinstance(payload, list):
        for item in payload:
            found |= _keys_everywhere(item)
    return found


async def test_option_pricing_leaks_no_cost_to_a_client_facing_role(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_sto_full_board", "acc_rack_discounted"],
        agent_cover_fee="25000",
    )
    ah = await _agent_headers(client, h)
    resp = await client.post(f"{API}/quotes/{quote['id']}/options/price", headers=ah)
    assert resp.status_code == 200, resp.text

    leaked = _keys_everywhere(resp.json()) & COST_KEYS
    assert not leaked, f"leaked {leaked} to a role without quote:read_cost"
    option = _option(resp.json(), "Coral Shoals")
    assert D(option["per_person"]) == D("18900")
    assert D(option["group_total"]) == D("472500")
    assert "rejected" in resp.json()


async def test_a_cost_reader_does_see_the_build_up(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(client, h, sample_catalogue, accommodations=["acc_rack_discounted"])
    option = _option(await _price(client, h, quote["id"]), "Mvule")
    assert D(option["build_up"]["cost_subtotal"]) == D("865800")
    assert D(option["supplier_paid_total"]) == D("795600")


async def test_pricing_refuses_a_quote_with_no_requested_meal_plan(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    record = await _client_record(client, h, sample_catalogue["residence_citizen"])
    quote = (
        await client.post(
            f"{API}/quotes",
            headers=h,
            json={
                "client_id": record["id"],
                "presentation_currency": "KES",
                "residence_category_id": sample_catalogue["residence_citizen"],
                "arrival_date": "2026-07-01",
                "departure_date": "2026-07-04",
                "pax_count": 25,
                "options": [
                    {"accommodation_id": sample_catalogue["acc_sto_full_board"]}
                ],
            },
        )
    ).json()
    resp = await client.post(f"{API}/quotes/{quote['id']}/options/price", headers=h)
    assert resp.status_code == 400
    assert "requested_meal_plan_id" in resp.text


async def test_pricing_refuses_a_quote_with_no_group_size(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    record = await _client_record(client, h, sample_catalogue["residence_citizen"])
    quote = (
        await client.post(
            f"{API}/quotes",
            headers=h,
            json={
                "client_id": record["id"],
                "presentation_currency": "KES",
                "residence_category_id": sample_catalogue["residence_citizen"],
                "arrival_date": "2026-07-01",
                "departure_date": "2026-07-04",
                "requested_meal_plan_id": sample_catalogue["meal_plan_fb"],
                "options": [
                    {"accommodation_id": sample_catalogue["acc_sto_full_board"]}
                ],
            },
        )
    ).json()
    resp = await client.post(f"{API}/quotes/{quote['id']}/options/price", headers=h)
    assert resp.status_code == 400
    assert "pax_count" in resp.text


async def test_pricing_refuses_a_quote_with_no_options(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    record = await _client_record(client, h, sample_catalogue["residence_citizen"])
    quote = (
        await client.post(
            f"{API}/quotes",
            headers=h,
            json={
                "client_id": record["id"],
                "presentation_currency": "KES",
                "residence_category_id": sample_catalogue["residence_citizen"],
                "arrival_date": "2026-07-01",
                "departure_date": "2026-07-04",
                "pax_count": 25,
                "requested_meal_plan_id": sample_catalogue["meal_plan_fb"],
            },
        )
    ).json()
    resp = await client.post(f"{API}/quotes/{quote['id']}/options/price", headers=h)
    assert resp.status_code == 400
    assert "no options" in resp.text


async def test_a_property_with_no_rates_is_an_internal_warning_not_a_refusal(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _quote(
        client,
        h,
        sample_catalogue,
        accommodations=["acc_villa"],
        pax=4,
        residence="residence_non_resident",
        currency="KES",
    )
    result = await _price(client, h, quote["id"])
    assert result["options"] == []
    assert result["rejected"] == []
    assert any("no rates are loaded" in w for w in result["warnings"])


async def _cohort_quote(client, h, ids, *, cohorts, accommodations, **over):
    record = await _client_record(client, h, ids["residence_citizen"])
    body = {
        "client_id": record["id"],
        "presentation_currency": "KES",
        "residence_category_id": ids["residence_citizen"],
        "arrival_date": "2026-07-01",
        "departure_date": "2026-07-04",
        "requested_meal_plan_id": ids["meal_plan_fb"],
        "cohorts": [
            {
                "residence_category_id": ids[f"residence_{residence}"],
                "traveller_type": kind,
                "headcount": n,
            }
            for residence, kind, n in cohorts
        ],
        "options": [
            {"accommodation_id": ids[key], "sort_order": order}
            for order, key in enumerate(accommodations, start=1)
        ],
    }
    body.update(over)
    resp = await client.post(f"{API}/quotes", headers=h, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_a_mixed_residency_group_takes_an_extra_room(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[("citizen", "adult", 3), ("non_resident", "adult", 3)],
        accommodations=["acc_sto_full_board"],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")

    assert option["rooms_required"] == 4
    assert option["per_person"] is None
    assert D(option["group_total"]) > 0


async def test_each_residency_is_costed_off_its_own_sheet(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    mixed = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[("citizen", "adult", 3), ("non_resident", "adult", 3)],
        accommodations=["acc_sto_full_board"],
    )
    residents_only = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[("citizen", "adult", 6)],
        accommodations=["acc_sto_full_board"],
    )

    mixed_option = _option(await _price(client, h, mixed["id"]), "Coral Shoals")
    resident_option = _option(
        await _price(client, h, residents_only["id"]), "Coral Shoals"
    )

    assert resident_option["rooms_required"] == 3
    assert mixed_option["rooms_required"] == 4
    assert D(mixed_option["group_total"]) > D(resident_option["group_total"])
    assert resident_option["per_person"] is not None


async def test_a_property_that_prices_only_one_residency_is_not_offered(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[("citizen", "adult", 2), ("non_resident", "adult", 2)],
        accommodations=["acc_rack_discounted"],
    )
    result = await _price(client, h, quote["id"])

    assert result["options"] == []
    assert result["rejected"] == []


async def test_the_headcount_and_the_rooming_come_from_one_place(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(
        client,
        h,
        ids,
        accommodations=["acc_sto_full_board"],
        pax=2,
        travellers=[
            {"traveller_type": "adult"},
            {"traveller_type": "child", "age": 8},
        ],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
    assert option["rooms_required"] == 1
    assert option["per_person"] is None


async def test_a_headcount_beside_a_few_named_guests_still_wins(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _quote(
        client,
        h,
        ids,
        accommodations=["acc_sto_full_board"],
        pax=25,
        travellers=[{"traveller_type": "adult"}, {"traveller_type": "adult"}],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")
    assert option["rooms_required"] == 13


def _by_cohort(option):
    return {
        (c["residence"], c["traveller_type"]): c for c in option["cohorts"]
    }


async def test_residents_and_non_residents_get_their_own_per_person_figure(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[("citizen", "adult", 3), ("non_resident", "adult", 3)],
        accommodations=["acc_sto_full_board"],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")

    assert option["per_person"] is None
    cohorts = _by_cohort(option)
    assert set(cohorts) == {("citizen", "adult"), ("non_resident", "adult")}

    resident = cohorts[("citizen", "adult")]
    visitor = cohorts[("non_resident", "adult")]
    assert resident["currency"] == "KES"
    assert visitor["currency"] == "USD"
    assert resident["headcount"] == 3
    assert visitor["headcount"] == 3
    assert D(resident["per_person"]) > 0
    assert D(visitor["per_person"]) > 0


async def test_every_cohort_total_is_its_per_person_times_its_headcount(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[
            ("citizen", "adult", 4),
            ("citizen", "child", 2),
            ("non_resident", "adult", 2),
        ],
        accommodations=["acc_sto_full_board"],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")

    assert len(option["cohorts"]) == 3
    for cohort in option["cohorts"]:
        assert D(cohort["total"]) == D(cohort["per_person"]) * cohort["headcount"], (
            cohort
        )


async def test_a_child_cohort_is_priced_apart_from_the_adults(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[("citizen", "adult", 4), ("citizen", "child", 2)],
        accommodations=["acc_sto_full_board"],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")

    cohorts = _by_cohort(option)
    assert set(cohorts) == {("citizen", "adult"), ("citizen", "child")}
    assert all(c["currency"] == "KES" for c in option["cohorts"])
    assert sum(c["headcount"] for c in option["cohorts"]) == 6


async def test_a_uniform_group_gets_one_cohort_matching_the_headline_figure(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[("citizen", "adult", 25)],
        accommodations=["acc_sto_full_board"],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")

    assert len(option["cohorts"]) == 1
    only = option["cohorts"][0]
    assert D(only["per_person"]) == D(option["per_person"])
    assert D(only["total"]) == D(option["group_total"])
    assert only["currency"] == option["currency"] == "KES"


async def test_the_rate_behind_a_converted_total_is_disclosed(
    client, admin_tokens, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    quote = await _cohort_quote(
        client,
        h,
        ids,
        cohorts=[("citizen", "adult", 2), ("non_resident", "adult", 2)],
        accommodations=["acc_sto_full_board"],
    )
    option = _option(await _price(client, h, quote["id"]), "Coral Shoals")

    assert option["conversions"].get("USD/KES") == "130.00000000"


async def test_a_hole_between_seasons_says_so_rather_than_blaming_capacity(
    client, admin_tokens, sample_catalogue
):
    import uuid as _uuid
    from datetime import date as _date

    from sqlalchemy import select as _select

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

    h, ids = _h(admin_tokens), sample_catalogue
    tag = _uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        dest = (await db.execute(_select(Destination).limit(1))).scalar_one()
        fb = (
            await db.execute(_select(MealPlan).where(MealPlan.code == "FB"))
        ).scalar_one()
        rc = (
            await db.execute(
                _select(ResidenceCategory).where(ResidenceCategory.key == "citizen")
            )
        ).scalar_one()
        acc = Accommodation(
            name=f"Season Hole Lodge {tag}",
            slug=f"season-hole-{tag}",
            destination_id=dest.id,
            category="lodge",
        )
        db.add(acc)
        await db.flush()
        room = RoomType(
            accommodation_id=acc.id, name="Twin", code="TWN", max_occupancy=2
        )
        db.add(room)
        await db.flush()
        for starts, ends, amount in (
            (_date(2026, 10, 1), _date(2026, 10, 30), "31200"),
            (_date(2026, 11, 1), _date(2026, 12, 22), "29120"),
        ):
            for occupancy in (1, 2):
                db.add(
                    AccommodationRate(
                        accommodation_id=acc.id,
                        room_type_id=room.id,
                        meal_plan_id=fb.id,
                        residence_category_id=rc.id,
                        season_name="s",
                        occupancy=occupancy,
                        effective_from=starts,
                        effective_to=ends,
                        currency="KES",
                        rate_per_night=D(amount),
                        rate_kind="sto",
                    )
                )
        await db.commit()
        acc_id = str(acc.id)

    record = await _client_record(client, h, ids["residence_citizen"])
    body = {
        "client_id": record["id"],
        "presentation_currency": "KES",
        "residence_category_id": ids["residence_citizen"],
        "arrival_date": "2026-10-29",
        "departure_date": "2026-11-01",
        "pax_count": 2,
        "requested_meal_plan_id": ids["meal_plan_fb"],
        "options": [{"accommodation_id": acc_id}],
    }
    quote = await client.post(f"{API}/quotes", headers=h, json=body)
    assert quote.status_code == 201, quote.text
    result = await _price(client, h, quote.json()["id"])

    assert result["options"] == []
    joined = " ".join(result["warnings"])
    assert "2026-10-31" in joined, joined
    assert "gap between season windows" in joined, joined
    assert "could house" not in joined, joined

    body |= {"arrival_date": "2026-10-29", "departure_date": "2026-10-31"}
    ok = await client.post(f"{API}/quotes", headers=h, json=body)
    priced = await _price(client, h, ok.json()["id"])
    assert len(priced["options"]) == 1, priced

    async with AsyncSessionLocal() as db:
        for quote_id in {
            q
            for (q,) in (
                await db.execute(
                    _select(QuoteOption.quote_id).where(
                        QuoteOption.accommodation_id == _uuid.UUID(acc_id)
                    )
                )
            ).all()
        }:
            row = await db.get(Quote, quote_id)
            if row is not None:
                await db.delete(row)
        await db.flush()
        acc_row = await db.get(Accommodation, _uuid.UUID(acc_id))
        if acc_row is not None:
            await db.delete(acc_row)
        await db.commit()
