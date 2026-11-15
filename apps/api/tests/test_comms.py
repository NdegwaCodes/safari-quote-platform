from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.modules.comms.models import Communication
from app.modules.leads.models import Lead
from app.modules.leads.pipeline import (
    NEVER_CONTACTED,
    STALE,
    UNANSWERED,
)
from app.modules.quotes.models import Quote
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")

TODAY = date.today()
NOW = datetime.now(UTC)


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest_asyncio.fixture(loop_scope="session")
async def swept():
    made: list[str] = []
    yield made
    async with AsyncSessionLocal() as db:
        for lead_id in made:
            rows = (
                (
                    await db.execute(
                        select(Communication).where(
                            Communication.subject_id == uuid.UUID(lead_id)
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                await db.delete(row)
            await db.flush()
            lead = await db.get(Lead, uuid.UUID(lead_id))
            if lead is not None:
                await db.delete(lead)
        await db.commit()


async def _lead(client, h, swept, **over):
    body = {
        "contact_name": f"Enquirer {uuid.uuid4().hex[:6]}",
        "contact_email": unique_email("comm"),
        "source": "Website",
        "destination_interest": "Diani, second week of March",
    }
    body.update(over)
    created = await client.post(f"{API}/leads", headers=h, json=body)
    assert created.status_code == 201, created.text
    swept.append(created.json()["id"])
    return created.json()


async def _log(client, h, lead_id, **over):
    body = {
        "channel": "call",
        "direction": "outbound",
        "body": "Talked through the two beach options.",
    }
    body.update(over)
    posted = await client.post(
        f"{API}/leads/{lead_id}/communications", headers=h, json=body
    )
    assert posted.status_code == 201, posted.text
    return posted.json()


def _ago(**kw):
    return (NOW - timedelta(**kw)).isoformat()


async def test_a_call_is_logged_against_a_lead_and_read_back(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    entry = await _log(
        client,
        h,
        lead["id"],
        subject_line="Diani options",
        duration_minutes=12,
        reached=True,
    )
    assert entry["channel"] == "call"
    assert entry["direction"] == "outbound"
    assert entry["duration_minutes"] == 12

    read = await client.get(f"{API}/leads/{lead['id']}/communications", headers=h)
    assert read.status_code == 200, read.text
    payload = read.json()
    assert [one["id"] for one in payload["entries"]] == [entry["id"]]
    assert payload["summary"]["contacts"] == 1
    assert payload["summary"]["by_channel"] == {"call": 1}


async def test_when_it_happened_is_not_when_it_was_typed(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    entry = await _log(client, h, lead["id"], occurred_at=_ago(days=2))
    assert entry["occurred_at"][:10] == (TODAY - timedelta(days=2)).isoformat()
    assert entry["created_at"][:10] == TODAY.isoformat()


async def test_a_conversation_cannot_be_logged_before_it_happens(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    refused = await client.post(
        f"{API}/leads/{lead['id']}/communications",
        headers=h,
        json={
            "channel": "call",
            "direction": "outbound",
            "body": "Will call about the villa.",
            "occurred_at": (NOW + timedelta(days=1)).isoformat(),
        },
    )
    assert refused.status_code == 400, refused.text
    assert "has not happened yet" in refused.text


async def test_an_entry_with_no_words_is_refused(client, admin_tokens, swept):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    refused = await client.post(
        f"{API}/leads/{lead['id']}/communications",
        headers=h,
        json={"channel": "call", "direction": "outbound", "body": "   "},
    )
    assert refused.status_code == 400, refused.text
    assert "Say what was said" in refused.text


async def test_an_unknown_direction_is_refused_with_the_three_that_work(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    refused = await client.post(
        f"{API}/leads/{lead['id']}/communications",
        headers=h,
        json={"channel": "email", "direction": "received", "body": "Replied."},
    )
    assert refused.status_code == 400, refused.text
    assert "not a direction" in refused.text


async def test_nothing_can_be_logged_against_something_that_is_not_there(
    client, admin_tokens
):
    h = _h(admin_tokens)
    refused = await client.post(
        f"{API}/leads/{uuid.uuid4()}/communications",
        headers=h,
        json={"channel": "call", "direction": "outbound", "body": "Spoke."},
    )
    assert refused.status_code == 404, refused.text


async def test_a_conversation_can_only_be_about_the_four_things(
    client, admin_tokens
):
    h = _h(admin_tokens)
    refused = await client.post(
        f"{API}/suppliers/{uuid.uuid4()}/communications",
        headers=h,
        json={"channel": "call", "direction": "outbound", "body": "Spoke."},
    )
    assert refused.status_code == 400, refused.text
    assert "not something a conversation can be about" in refused.text


async def test_logging_a_call_stamps_the_lead(client, admin_tokens, swept):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    await _log(client, h, lead["id"], occurred_at=_ago(days=1))

    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        assert row.last_contact_at is not None
        assert row.last_inbound_at is None


async def test_a_reply_stamps_the_inbound_column_too(client, admin_tokens, swept):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    await _log(client, h, lead["id"], direction="inbound", channel="email",
               body="Yes, the second week works for us.")
    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        assert row.last_inbound_at is not None


async def test_a_tuesday_call_written_up_on_friday_does_not_move_last_contact_back(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    await _log(client, h, lead["id"], occurred_at=_ago(hours=2))
    await _log(client, h, lead["id"], occurred_at=_ago(days=4))

    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        assert row.last_contact_at is not None
        assert (NOW - row.last_contact_at) < timedelta(hours=3)


async def test_an_internal_note_is_not_contact_with_the_client(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    await _log(
        client,
        h,
        lead["id"],
        channel="note",
        direction="internal",
        body="Her sister is the one paying.",
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        assert row.last_contact_at is None

    listed = await client.get(f"{API}/leads/attention", headers=h)
    assert listed.status_code == 200, listed.text
    mine = _find(listed.json(), lead["id"])
    reasons = {one["code"] for one in mine["reasons"]}
    assert NEVER_CONTACTED in reasons
    never = next(one for one in mine["reasons"] if one["code"] == NEVER_CONTACTED)
    assert "though there are notes on it" in never["message"]


async def test_an_unanswered_enquiry_is_the_first_thing_on_the_morning_list(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    ignored = await _lead(client, h, swept)
    answered = await _lead(client, h, swept)
    await _log(client, h, answered["id"], occurred_at=_ago(hours=1))

    listed = await client.get(f"{API}/leads/attention", headers=h)
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    codes = {
        one["lead"]["id"]: {r["code"] for r in one["reasons"]} for one in payload
    }
    assert NEVER_CONTACTED in codes[ignored["id"]]
    assert NEVER_CONTACTED not in codes.get(answered["id"], set())

    ranked = [one["lead"]["id"] for one in payload]
    first_never = min(
        index
        for index, one in enumerate(payload)
        if NEVER_CONTACTED in {r["code"] for r in one["reasons"]}
    )
    last_never = max(
        index
        for index, one in enumerate(payload)
        if NEVER_CONTACTED in {r["code"] for r in one["reasons"]}
    )
    others = [
        index
        for index, one in enumerate(payload)
        if NEVER_CONTACTED not in {r["code"] for r in one["reasons"]}
    ]
    assert first_never == 0
    assert all(index > last_never for index in others)
    assert ignored["id"] in ranked


async def test_staleness_is_measured_by_contact_and_not_by_stage_movement(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    await _log(client, h, lead["id"], occurred_at=_ago(days=21))

    listed = await client.get(
        f"{API}/leads/attention?stale_after_days=14", headers=h
    )
    mine = _find(listed.json(), lead["id"])
    stale = next(one for one in mine["reasons"] if one["code"] == STALE)
    assert stale["days"] == 21
    assert "has not been contacted for" in stale["message"]


async def test_a_lead_chased_into_silence_is_reported_on_the_list(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    for days in (12, 9, 5):
        await _log(client, h, lead["id"], channel="email", occurred_at=_ago(days=days))

    listed = await client.get(f"{API}/leads/attention", headers=h)
    mine = _find(listed.json(), lead["id"])
    quiet = next(one for one in mine["reasons"] if one["code"] == UNANSWERED)
    assert quiet["days"] == 3
    assert "never replied" in quiet["message"]


async def test_a_reply_resets_the_chase_count(client, admin_tokens, swept):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    for days in (12, 9, 5):
        await _log(client, h, lead["id"], channel="email", occurred_at=_ago(days=days))
    await _log(
        client,
        h,
        lead["id"],
        channel="email",
        direction="inbound",
        body="Sorry for the delay — still interested.",
        occurred_at=_ago(days=1),
    )
    read = await client.get(f"{API}/leads/{lead['id']}/communications", headers=h)
    assert read.json()["summary"]["chases"] == 0
    assert read.json()["gone_quiet"] is None


async def test_a_call_can_set_the_leads_next_action_in_the_same_breath(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    when = (TODAY + timedelta(days=5)).isoformat()
    await _log(
        client,
        h,
        lead["id"],
        next_action_on=when,
        next_action_note="Send the Diani comparison.",
    )
    read = await client.get(f"{API}/leads/{lead['id']}", headers=h)
    assert read.json()["next_action_on"] == when
    assert read.json()["next_action_note"] == "Send the Diani comparison."


async def test_a_leads_timeline_gathers_the_clients_entries_too(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    made = await client.post(
        f"{API}/clients",
        headers=h,
        json={"name": "Timeline Co", "email": unique_email("timeline")},
    )
    assert made.status_code == 201, made.text
    client_id = made.json()["id"]
    lead = await _lead(client, h, swept, client_id=client_id)

    await _log(client, h, lead["id"], occurred_at=_ago(days=3))
    posted = await client.post(
        f"{API}/clients/{client_id}/communications",
        headers=h,
        json={
            "channel": "email",
            "direction": "inbound",
            "body": "Invoice received, thank you.",
            "occurred_at": _ago(days=1),
        },
    )
    assert posted.status_code == 201, posted.text

    read = await client.get(f"{API}/leads/{lead['id']}/communications", headers=h)
    payload = read.json()
    assert payload["summary"]["entries"] == 2
    assert payload["summary"]["last_inbound_at"] is not None
    assert payload["entries"][0]["subject"] == "client"

    theirs = await client.get(
        f"{API}/clients/{client_id}/communications", headers=h
    )
    assert theirs.json()["summary"]["entries"] == 1

    async with AsyncSessionLocal() as db:
        for row in (
            (
                await db.execute(
                    select(Communication).where(
                        Communication.subject_id == uuid.UUID(client_id)
                    )
                )
            )
            .scalars()
            .all()
        ):
            await db.delete(row)
        await db.commit()


async def test_a_call_about_a_quote_is_contact_with_that_quotes_lead(
    client, admin_tokens, swept, sample_catalogue
):
    h, ids = _h(admin_tokens), sample_catalogue
    lead = await _lead(client, h, swept)
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Quote Client {uuid.uuid4().hex[:6]}",
            "email": unique_email("quoteclient"),
            "residence_category_id": ids["residence_citizen"],
        },
    )
    quote = await client.post(
        f"{API}/quotes",
        headers=h,
        json={
            "client_id": record.json()["id"],
            "lead_id": lead["id"],
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

    posted = await client.post(
        f"{API}/quotes/{quote_id}/communications",
        headers=h,
        json={
            "channel": "email",
            "direction": "outbound",
            "subject_line": "Your Diani proposal",
            "body": "Sent the proposal with both options.",
            "occurred_at": _ago(hours=3),
        },
    )
    assert posted.status_code == 201, posted.text

    read = await client.get(f"{API}/leads/{lead['id']}/communications", headers=h)
    assert [one["subject"] for one in read.json()["entries"]] == ["quote"]
    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        assert row.last_contact_at is not None

    listed = await client.get(f"{API}/leads/attention", headers=h)
    mine = _find(listed.json(), lead["id"])
    assert NEVER_CONTACTED not in {one["code"] for one in mine["reasons"]}

    async with AsyncSessionLocal() as db:
        for entry in (
            (
                await db.execute(
                    select(Communication).where(
                        Communication.subject_id == uuid.UUID(quote_id)
                    )
                )
            )
            .scalars()
            .all()
        ):
            await db.delete(entry)
        await db.flush()
        stale_quote = await db.get(Quote, uuid.UUID(quote_id))
        if stale_quote is not None:
            await db.delete(stale_quote)
        await db.commit()


async def test_a_client_level_call_does_not_stamp_an_arbitrary_lead(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    made = await client.post(
        f"{API}/clients",
        headers=h,
        json={"name": "Repeat Co", "email": unique_email("repeat")},
    )
    client_id = made.json()["id"]
    lead = await _lead(client, h, swept, client_id=client_id)
    await client.post(
        f"{API}/clients/{client_id}/communications",
        headers=h,
        json={"channel": "call", "direction": "outbound", "body": "Rang about 2027."},
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        assert row.last_contact_at is None
        for entry in (
            (
                await db.execute(
                    select(Communication).where(
                        Communication.subject_id == uuid.UUID(client_id)
                    )
                )
            )
            .scalars()
            .all()
        ):
            await db.delete(entry)
        await db.commit()


async def test_an_entry_can_be_amended_and_says_that_it_was(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    entry = await _log(client, h, lead["id"])
    amended = await client.patch(
        f"{API}/communications/{entry['id']}",
        headers=h,
        json={"body": "Talked through both beach options and the transfer."},
    )
    assert amended.status_code == 200, amended.text
    assert amended.json()["amended_at"] is not None
    assert "transfer" in amended.json()["body"]


async def test_amending_cannot_move_an_entry_to_another_lead(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    entry = await _log(client, h, lead["id"])
    refused = await client.patch(
        f"{API}/communications/{entry['id']}",
        headers=h,
        json={"subject_id": str(uuid.uuid4())},
    )
    assert refused.status_code in (200, 422)
    read = await client.get(f"{API}/leads/{lead['id']}/communications", headers=h)
    assert read.json()["summary"]["entries"] == 1


async def test_amending_still_obeys_the_rules(client, admin_tokens, swept):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    entry = await _log(client, h, lead["id"], reached=True, duration_minutes=8)
    refused = await client.patch(
        f"{API}/communications/{entry['id']}",
        headers=h,
        json={"reached": False},
    )
    assert refused.status_code == 400, refused.text
    assert "not answered has no length" in refused.text


async def test_a_wrong_entry_is_voided_and_stays_visible(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    entry = await _log(client, h, lead["id"], occurred_at=_ago(days=1))
    voided = await client.post(
        f"{API}/communications/{entry['id']}/void",
        headers=h,
        json={"reason": "Logged against the wrong enquiry."},
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["voided_at"] is not None

    read = await client.get(f"{API}/leads/{lead['id']}/communications", headers=h)
    payload = read.json()
    assert payload["summary"]["entries"] == 1
    assert payload["summary"]["contacts"] == 0
    assert payload["summary"]["last_contact_at"] is None

    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        assert row.last_contact_at is None


async def test_voiding_needs_a_reason(client, admin_tokens, swept):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    entry = await _log(client, h, lead["id"])
    refused = await client.post(
        f"{API}/communications/{entry['id']}/void",
        headers=h,
        json={"reason": "   "},
    )
    assert refused.status_code == 400, refused.text


async def test_a_voided_entry_cannot_be_amended(client, admin_tokens, swept):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    entry = await _log(client, h, lead["id"])
    await client.post(
        f"{API}/communications/{entry['id']}/void",
        headers=h,
        json={"reason": "Wrong lead."},
    )
    refused = await client.patch(
        f"{API}/communications/{entry['id']}",
        headers=h,
        json={"body": "Actually it was about Watamu."},
    )
    assert refused.status_code == 400, refused.text
    assert "voided" in refused.text


async def test_the_stamps_can_be_rebuilt_and_agree_with_what_logging_kept(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    lead = await _lead(client, h, swept)
    await _log(client, h, lead["id"], occurred_at=_ago(days=6))
    await _log(
        client,
        h,
        lead["id"],
        channel="email",
        direction="inbound",
        body="Looks good.",
        occurred_at=_ago(days=2),
    )

    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        incremental = (row.last_contact_at, row.last_inbound_at)
        row.last_contact_at = None
        row.last_inbound_at = datetime(2020, 1, 1, tzinfo=UTC)
        await db.commit()

    rebuilt = await client.post(
        f"{API}/leads/{lead['id']}/recompute-contact", headers=h
    )
    assert rebuilt.status_code == 200, rebuilt.text
    async with AsyncSessionLocal() as db:
        row = await db.get(Lead, uuid.UUID(lead["id"]))
        assert row is not None
        assert (row.last_contact_at, row.last_inbound_at) == incremental


async def test_the_pipeline_reports_a_first_response_time_and_the_ones_never_answered(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    answered = await _lead(client, h, swept)
    await _log(client, h, answered["id"])
    await _lead(client, h, swept)

    report = await client.get(f"{API}/leads/pipeline", headers=h)
    assert report.status_code == 200, report.text
    payload = report.json()
    assert payload["median_first_response_hours"] is not None
    assert payload["never_answered"] >= 1


async def test_an_agent_logs_calls_but_cannot_rewrite_the_record_of_one(
    client, admin_tokens, swept
):
    h = _h(admin_tokens)
    email = unique_email("agent")
    made = await client.post(
        f"{API}/users",
        headers=h,
        json={
            "email": email,
            "password": "AgentPass123",
            "role_keys": ["sales_agent"],
        },
    )
    assert made.status_code in (200, 201), made.text
    logged_in = await client.post(
        f"{API}/auth/login", data={"username": email, "password": "AgentPass123"}
    )
    agent_h = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}

    lead = await _lead(client, h, swept)
    entry = await client.post(
        f"{API}/leads/{lead['id']}/communications",
        headers=agent_h,
        json={"channel": "call", "direction": "outbound", "body": "Spoke."},
    )
    assert entry.status_code == 201, entry.text
    assert (
        await client.get(f"{API}/leads/{lead['id']}/communications", headers=agent_h)
    ).status_code == 200
    refused = await client.patch(
        f"{API}/communications/{entry.json()['id']}",
        headers=agent_h,
        json={"body": "Actually about Watamu."},
    )
    assert refused.status_code == 403, refused.text
    refused = await client.post(
        f"{API}/communications/{entry.json()['id']}/void",
        headers=agent_h,
        json={"reason": "Wrong lead."},
    )
    assert refused.status_code == 403, refused.text


def _find(payload: list[dict], lead_id: str) -> dict:
    for one in payload:
        if one["lead"]["id"] == lead_id:
            return one
    raise AssertionError(f"lead {lead_id} is not on the attention list")
