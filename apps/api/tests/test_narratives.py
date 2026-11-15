from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.integrations.narrative import (
    ACCOMMODATION,
    DESTINATION,
    HAND,
    Brief,
    Draft,
    NarrativeUnavailable,
    UnavailableProvider,
)
from app.modules.accommodations.models import Accommodation
from app.modules.narratives.models import APPROVED, DRAFT, REJECTED, Narrative
from app.modules.narratives.service import NarrativeService
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")

D = Decimal


class StubProvider:

    name = "stub"

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.briefs: list[Brief] = []

    async def write(self, brief: Brief) -> Draft:
        if self.fail:
            raise NarrativeUnavailable("the stub is having a day off")
        self.briefs.append(brief)
        return Draft(
            text=f"STUB<{brief.name}|{brief.place}|{'/'.join(brief.meal_plans)}>",
            provider=self.name,
            model="stub-1",
        )


@pytest_asyncio.fixture(loop_scope="session")
async def written_off():
    yield
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(Narrative).where(Narrative.provider.in_(["stub", HAND, "stub+hand"]))
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await db.delete(row)
        await db.commit()


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def test_the_brief_carries_facts_from_the_catalogue(
    client, admin_tokens, sample_catalogue
):
    async with AsyncSessionLocal() as db:
        brief = await NarrativeService(db).brief_for(
            ACCOMMODATION,
            uuid.UUID(sample_catalogue["acc_sto_full_board"]),
            steer="Ask about the reef.",
        )
    assert brief.subject == ACCOMMODATION
    assert "Coral Shoals" in brief.name
    assert brief.category
    assert "Diani" in brief.place
    assert brief.meal_plans, brief
    assert all(plan for plan in brief.meal_plans)
    assert brief.room_types
    assert brief.steer == "Ask about the reef."


async def test_a_brief_refuses_to_be_about_nothing():
    with pytest.raises(ValueError, match="something to be about"):
        Brief(subject=ACCOMMODATION, name="")
    with pytest.raises(ValueError, match="unknown narrative subject"):
        Brief(subject="hotel_chain", name="Somewhere")
    with pytest.raises(ValueError, match="words must be positive"):
        Brief(subject=DESTINATION, name="Diani", words=0)


async def test_a_draft_must_say_what_produced_it():
    with pytest.raises(ValueError, match="must say what produced it"):
        Draft(text="Lovely.", provider="")
    with pytest.raises(ValueError, match="no text is not a draft"):
        Draft(text="   ", provider="stub")


async def test_the_default_provider_refuses_out_loud():
    with pytest.raises(NarrativeUnavailable, match="No narrative provider"):
        await UnavailableProvider().write(Brief(subject=DESTINATION, name="Diani"))


async def test_generating_with_no_provider_configured_is_refused(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    refused = await client.post(
        f"{API}/accommodations/{sample_catalogue['acc_sto_full_board']}"
        f"/narratives/generate",
        headers=h,
        json={"steer": "Mention the reef."},
    )
    assert refused.status_code == 400, refused.text
    message = refused.json()["error"]["message"]
    assert "No narrative provider is configured" in message
    assert "same review" in message


async def test_a_generated_draft_is_a_draft_and_carries_its_provenance(
    client, admin_tokens, sample_catalogue, written_off
):
    stub = StubProvider()
    async with AsyncSessionLocal() as db:
        row = await NarrativeService(db, provider=stub).generate(
            ACCOMMODATION,
            uuid.UUID(sample_catalogue["acc_sto_full_board"]),
            actor_id=None,
            steer="Mention the reef.",
        )
    assert row.status == DRAFT
    assert row.provider == "stub"
    assert row.model == "stub-1"
    assert row.brief["steer"] == "Mention the reef."
    assert row.brief["meal_plans"]
    assert not row.is_printable
    assert stub.briefs and stub.briefs[0].name == row.brief["name"]


async def test_an_unapproved_draft_never_reaches_the_document(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    async with AsyncSessionLocal() as db:
        await NarrativeService(db, provider=StubProvider()).generate(
            ACCOMMODATION,
            uuid.UUID(ids["acc_sto_full_board"]),
            actor_id=None,
        )
    html = await _issued_document(client, h, ids)
    assert "STUB<" not in html


async def test_approved_copy_reaches_the_document_and_wins(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    subject_id = uuid.UUID(ids["acc_sto_full_board"])
    async with AsyncSessionLocal() as db:
        accommodation = await db.get(Accommodation, subject_id)
        accommodation.blurb = "THE OLD BLURB."
        await db.commit()
        service = NarrativeService(db, provider=StubProvider())
        draft = await service.generate(ACCOMMODATION, subject_id, actor_id=None)
        await service.approve(draft.id, actor_id=None)

    html = await _issued_document(client, h, ids)
    assert "STUB&lt;" in html or "STUB<" in html
    assert "THE OLD BLURB" not in html

    async with AsyncSessionLocal() as db:
        accommodation = await db.get(Accommodation, subject_id)
        accommodation.blurb = None
        await db.commit()


async def test_approval_supersedes_the_standing_copy_and_keeps_it(
    client, admin_tokens, sample_catalogue, written_off
):
    subject_id = uuid.UUID(sample_catalogue["acc_sto_full_board"])
    async with AsyncSessionLocal() as db:
        service = NarrativeService(db)
        first = await service.compose(
            ACCOMMODATION, subject_id, text="The first description.", actor_id=None
        )
        await service.approve(first.id, actor_id=None)
        second = await service.compose(
            ACCOMMODATION, subject_id, text="The second description.", actor_id=None
        )
        await service.approve(second.id, actor_id=None)

        standing = await service.printable(ACCOMMODATION, subject_id)
        assert standing is not None
        assert standing.text == "The second description."

        replaced = await db.get(Narrative, first.id)
        assert replaced.status == APPROVED
        assert replaced.superseded_at is not None
        assert not replaced.is_printable
        history = await service.history(ACCOMMODATION, subject_id)
        assert first.id in [row.id for row in history]


async def test_an_agents_own_writing_takes_the_same_path(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    written = await client.post(
        f"{API}/accommodations/{ids['acc_sto_full_board']}/narratives",
        headers=h,
        json={"text": "A HAND WRITTEN PARAGRAPH."},
    )
    assert written.status_code == 201, written.text
    body = written.json()
    assert body["status"] == DRAFT
    assert body["provider"] == HAND

    html = await _issued_document(client, h, ids)
    assert "A HAND WRITTEN PARAGRAPH" not in html


async def test_a_model_draft_edited_by_a_person_records_both(
    client, admin_tokens, sample_catalogue, written_off
):
    subject_id = uuid.UUID(sample_catalogue["acc_sto_full_board"])
    async with AsyncSessionLocal() as db:
        service = NarrativeService(db, provider=StubProvider())
        draft = await service.generate(ACCOMMODATION, subject_id, actor_id=None)
        revised = await service.revise(
            draft.id, text="The version a person actually wrote.", actor_id=None
        )
    assert revised.provider == f"stub+{HAND}"
    assert revised.text == "The version a person actually wrote."
    assert revised.status == DRAFT


async def test_approved_copy_cannot_be_edited(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    written = await client.post(
        f"{API}/accommodations/{ids['acc_sto_full_board']}/narratives",
        headers=h,
        json={"text": "Approved and final."},
    )
    narrative_id = written.json()["id"]
    approved = await client.post(
        f"{API}/narratives/{narrative_id}/approve", headers=h
    )
    assert approved.status_code == 200, approved.text

    refused = await client.patch(
        f"{API}/narratives/{narrative_id}",
        headers=h,
        json={"text": "Quietly changed afterwards."},
    )
    assert refused.status_code == 400, refused.text
    assert "not a draft" in refused.json()["error"]["message"]


async def test_a_rejected_draft_is_kept_with_its_reason(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    written = await client.post(
        f"{API}/accommodations/{ids['acc_sto_full_board']}/narratives",
        headers=h,
        json={"text": "Claims a spa the property does not have."},
    )
    narrative_id = written.json()["id"]
    rejected = await client.post(
        f"{API}/narratives/{narrative_id}/reject",
        headers=h,
        json={"note": "No spa. Check the facilities list before writing."},
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["status"] == REJECTED
    assert "No spa" in body["review_note"]
    assert body["reviewed_at"] is not None

    listed = await client.get(
        f"{API}/accommodations/{ids['acc_sto_full_board']}/narratives", headers=h
    )
    assert narrative_id in [row["id"] for row in listed.json()]

    revived = await client.post(
        f"{API}/narratives/{narrative_id}/approve", headers=h
    )
    assert revived.status_code == 400, revived.text
    assert "already turned down" in revived.json()["error"]["message"]


async def test_an_approved_narrative_cannot_be_rejected_out_from_under_a_proposal(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    written = await client.post(
        f"{API}/accommodations/{ids['acc_sto_full_board']}/narratives",
        headers=h,
        json={"text": "On a proposal already."},
    )
    narrative_id = written.json()["id"]
    await client.post(f"{API}/narratives/{narrative_id}/approve", headers=h)
    refused = await client.post(
        f"{API}/narratives/{narrative_id}/reject", headers=h, json={}
    )
    assert refused.status_code == 400, refused.text
    assert "Approve a replacement" in refused.json()["error"]["message"]


async def test_the_review_queue_is_readable(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    written = await client.post(
        f"{API}/accommodations/{ids['acc_sto_full_board']}/narratives",
        headers=h,
        json={"text": "Waiting for somebody to read it."},
    )
    assert written.status_code == 201, written.text
    queue = await client.get(f"{API}/narratives", headers=h, params={"status": "draft"})
    assert queue.status_code == 200, queue.text
    assert written.json()["id"] in [row["id"] for row in queue.json()]

    bad = await client.get(
        f"{API}/narratives", headers=h, params={"status": "published"}
    )
    assert bad.status_code == 400, bad.text


async def test_a_destination_narrative_works_the_same_way(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    written = await client.post(
        f"{API}/destinations/{ids['destination_diani']}/narratives",
        headers=h,
        json={"text": "A description of the coast."},
    )
    assert written.status_code == 201, written.text
    assert written.json()["subject"] == DESTINATION
    approved = await client.post(
        f"{API}/narratives/{written.json()['id']}/approve", headers=h
    )
    assert approved.status_code == 200, approved.text


async def test_approval_is_its_own_permission(
    client, admin_tokens, sample_catalogue, written_off
):
    from app.modules.rbac.permissions import PERMISSIONS, ROLE_DEFINITIONS

    assert "narrative:manage" in PERMISSIONS
    assert "narrative:approve" in PERMISSIONS
    assert "narrative:approve" in ROLE_DEFINITIONS["admin"]["permissions"]
    assert "narrative:read" in PERMISSIONS


async def _issued_document(client, h, ids) -> str:
    quote_id = await _issued_quote(client, h, ids)
    page = await client.get(f"{API}/quotes/{quote_id}/document.html", headers=h)
    assert page.status_code == 200, page.text
    return page.text


async def _issued_quote(client, h, ids) -> str:
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Narrative Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("narrative"),
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
    return quote_id


async def test_an_issued_proposal_keeps_the_words_it_went_out_with(
    client, admin_tokens, sample_catalogue, written_off
):
    h, ids = _h(admin_tokens), sample_catalogue
    subject_id = uuid.UUID(ids["acc_sto_full_board"])
    async with AsyncSessionLocal() as db:
        service = NarrativeService(db)
        first = await service.compose(
            ACCOMMODATION, subject_id, text="AS ISSUED, THE FIRST WORDS.", actor_id=None
        )
        await service.approve(first.id, actor_id=None)

    quote_id = await _issued_quote(client, h, ids)
    page = await client.get(f"{API}/quotes/{quote_id}/document.html", headers=h)
    assert "AS ISSUED, THE FIRST WORDS." in page.text

    async with AsyncSessionLocal() as db:
        service = NarrativeService(db)
        second = await service.compose(
            ACCOMMODATION, subject_id, text="WRITTEN AFTERWARDS.", actor_id=None
        )
        await service.approve(second.id, actor_id=None)

    again = await client.get(f"{API}/quotes/{quote_id}/document.html", headers=h)
    assert "AS ISSUED, THE FIRST WORDS." in again.text
    assert "WRITTEN AFTERWARDS." not in again.text

    fresh = await _issued_quote(client, h, ids)
    latest = await client.get(f"{API}/quotes/{fresh}/document.html", headers=h)
    assert "WRITTEN AFTERWARDS." in latest.text
