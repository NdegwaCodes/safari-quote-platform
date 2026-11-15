from __future__ import annotations

import io
import uuid

import pdfplumber
import pytest

from app.core.config import settings
from app.integrations.pdf_render import PdfRenderError
from app.modules.documents.pdf import ChromiumPdfRenderer, find_browser
from app.modules.documents.service import QuotationDocumentService
from tests.conftest import unique_email

API = settings.API_V1_STR
pytestmark = pytest.mark.asyncio(loop_scope="session")

no_browser = pytest.mark.skipif(
    find_browser() is None,
    reason="no Chromium-family browser on this host; PDF rendering needs one",
)

ci_pdf_hang = pytest.mark.skipif(
    settings.PDF_TESTS_KNOWN_TO_HANG,
    reason="known hang in Chromium's print-to-pdf on this CI runner; see .github/workflows/ci.yml",
)


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _issued_quote(client, h, ids, *, options=None, **over):
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Pdf Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("pdf"),
            "residence_category_id": ids["residence_citizen"],
        },
    )
    assert record.status_code == 201, record.text
    body = {
        "client_id": record.json()["id"],
        "presentation_currency": "KES",
        "residence_category_id": ids["residence_citizen"],
        "arrival_date": "2026-07-01",
        "departure_date": "2026-07-04",
        "pax_count": 25,
        "requested_meal_plan_id": ids["meal_plan_fb"],
        "document_title": "Corporate Coastal Retreat",
        "options": options
        or [
            {"accommodation_id": ids["acc_sto_full_board"], "is_recommended": True},
            {"accommodation_id": ids["acc_rack_discounted"], "agent_cover_fee": "25000"},
        ],
    }
    body.update(over)
    created = await client.post(f"{API}/quotes", headers=h, json=body)
    assert created.status_code == 201, created.text
    quote = created.json()
    issued = await client.post(f"{API}/quotes/{quote['id']}/issue", headers=h)
    assert issued.status_code == 200, issued.text
    return quote


def pdf_text(payload: bytes) -> str:
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def pdf_pages(payload: bytes) -> int:
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        return len(pdf.pages)


def test_the_command_prints_a_document_and_nothing_else(tmp_path):
    renderer = ChromiumPdfRenderer(binary="/usr/bin/chromium")
    command = renderer._command(
        tmp_path / "doc.html", tmp_path / "doc.pdf", tmp_path
    )
    assert command[0] == "/usr/bin/chromium"
    assert "--headless" in command
    assert "--disable-gpu" in command
    assert "--no-pdf-header-footer" in command
    assert any(c.startswith("--user-data-dir=") for c in command)
    assert any(c.startswith("--print-to-pdf=") for c in command)
    assert command[-1].startswith("file://")


def test_the_sandbox_is_only_disabled_when_asked(monkeypatch, tmp_path):
    renderer = ChromiumPdfRenderer(binary="/usr/bin/chromium")
    args = (tmp_path / "a.html", tmp_path / "a.pdf", tmp_path)
    monkeypatch.setattr(settings, "PDF_BROWSER_NO_SANDBOX", False)
    assert "--no-sandbox" not in renderer._command(*args)
    monkeypatch.setattr(settings, "PDF_BROWSER_NO_SANDBOX", True)
    assert "--no-sandbox" in renderer._command(*args)


def test_a_renderer_with_no_browser_reports_itself(monkeypatch):
    monkeypatch.setattr(
        "app.modules.documents.pdf.find_browser", lambda: None, raising=True
    )
    assert ChromiumPdfRenderer().is_available() is False


def test_a_configured_path_is_never_second_guessed(monkeypatch):
    monkeypatch.setattr(settings, "PDF_BROWSER_PATH", "/nowhere/chromium")
    assert find_browser() is None


def test_the_filename_carries_the_quote_number_and_version():
    assert (
        QuotationDocumentService.filename("HTQ-2026-0037", 2) == "HTQ-2026-0037-v2.pdf"
    )


async def test_a_missing_renderer_is_explained_not_a_crash(
    client, admin_tokens, sample_catalogue, monkeypatch
):
    h = _h(admin_tokens)
    quote = await _issued_quote(client, h, sample_catalogue)
    monkeypatch.setattr(
        "app.modules.documents.pdf.find_browser", lambda: None, raising=True
    )
    resp = await client.get(f"{API}/quotes/{quote['id']}/document.pdf", headers=h)
    assert resp.status_code == 400
    assert "No PDF renderer is available" in resp.text
    html = await client.get(f"{API}/quotes/{quote['id']}/document.html", headers=h)
    assert html.status_code == 200


async def test_a_renderer_that_fails_is_reported_with_the_engine_name(
    client, admin_tokens, sample_catalogue, monkeypatch
):

    class Broken:
        name = "broken-engine"

        def is_available(self) -> bool:
            return True

        async def render(self, html: str, *, timeout_seconds: int = 60) -> bytes:
            raise PdfRenderError("broken-engine produced no PDF (exit 1)")

    h = _h(admin_tokens)
    quote = await _issued_quote(client, h, sample_catalogue)
    monkeypatch.setattr(
        "app.modules.documents.pdf.default_renderer", lambda: Broken(), raising=True
    )
    monkeypatch.setattr(
        "app.modules.documents.service.default_renderer", lambda: Broken(), raising=True
    )
    resp = await client.get(f"{API}/quotes/{quote['id']}/document.pdf", headers=h)
    assert resp.status_code == 400
    assert "could not be printed" in resp.text
    assert "broken-engine" in resp.text


@no_browser
@ci_pdf_hang
async def test_the_quotation_prints_to_a_real_pdf(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _issued_quote(client, h, sample_catalogue)
    resp = await client.get(f"{API}/quotes/{quote['id']}/document.pdf", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF-")
    assert (
        resp.headers["content-disposition"]
        == f'attachment; filename="{quote["quote_number"]}-v1.pdf"'
    )
    assert pdf_pages(resp.content) == 7


@no_browser
@ci_pdf_hang
async def test_the_printed_pdf_carries_the_quote_number_and_validity(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _issued_quote(client, h, sample_catalogue)
    resp = await client.get(f"{API}/quotes/{quote['id']}/document.pdf", headers=h)
    text = pdf_text(resp.content)

    assert quote["quote_number"] in text
    stored = (await client.get(f"{API}/quotes/{quote['id']}", headers=h)).json()
    lowered = text.lower()
    assert "valid until" in lowered
    assert "issued" in lowered
    year, _month, day = stored["valid_until"].split("-")
    assert year in text
    assert day.lstrip("0") in text


@no_browser
@ci_pdf_hang
async def test_the_printed_pdf_contains_no_internal_figure(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _issued_quote(client, h, sample_catalogue)
    resp = await client.get(f"{API}/quotes/{quote['id']}/document.pdf", headers=h)
    text = pdf_text(resp.content)

    forbidden = [
        "936,000",
        "795,600",
        "865,800",
        "70,200",
        "43,290",
        "218,181",
        "25,000",
        "343,500",
        "86,562",
    ]
    leaked = [figure for figure in forbidden if figure in text]
    assert not leaked, f"internal figures in the printed PDF: {leaked}"

    assert "17,900" in text
    assert "447,500" in text
    assert "46,100" in text
    assert "1,152,500" in text


@no_browser
@ci_pdf_hang
async def test_the_printed_pdf_embeds_its_photographs(
    client, admin_tokens, sample_catalogue
):
    from tests.test_documents import png_bytes

    h = _h(admin_tokens)
    hero = await client.post(
        f"{API}/accommodations/{sample_catalogue['acc_sto_full_board']}/images",
        headers=h,
        files={"file": ("pdfhero.png", png_bytes((200, 40, 40), (40, 30)), "image/png")},
        data={"is_hero": "true"},
    )
    assert hero.status_code == 201, hero.text

    quote = await _issued_quote(client, h, sample_catalogue)
    resp = await client.get(f"{API}/quotes/{quote['id']}/document.pdf", headers=h)
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        embedded = sum(len(page.images) for page in pdf.pages)
    assert embedded > 0, "the photographs did not reach the PDF"


@no_browser
@ci_pdf_hang
async def test_an_earlier_version_still_prints_as_it_was_sent(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _issued_quote(
        client,
        h,
        sample_catalogue,
        options=[
            {
                "accommodation_id": sample_catalogue["acc_sto_full_board"],
                "is_recommended": True,
            }
        ],
    )
    await client.patch(
        f"{API}/quotes/{quote['id']}/status", headers=h, json={"status": "draft"}
    )
    stored = (await client.get(f"{API}/quotes/{quote['id']}", headers=h)).json()
    await client.patch(
        f"{API}/quotes/{quote['id']}/options/{stored['options'][0]['id']}",
        headers=h,
        json={"agent_cover_fee": "25000"},
    )
    assert (
        await client.post(f"{API}/quotes/{quote['id']}/issue", headers=h)
    ).status_code == 200

    latest = await client.get(f"{API}/quotes/{quote['id']}/document.pdf", headers=h)
    first = await client.get(
        f"{API}/quotes/{quote['id']}/document.pdf", headers=h, params={"version": 1}
    )
    assert "472,500" in pdf_text(latest.content)
    assert "447,500" in pdf_text(first.content)
    assert "472,500" not in pdf_text(first.content)
    assert "-v2.pdf" in latest.headers["content-disposition"]
    assert "-v1.pdf" in first.headers["content-disposition"]


@no_browser
@ci_pdf_hang
async def test_the_pdf_can_be_served_inline_for_a_preview(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _issued_quote(client, h, sample_catalogue)
    resp = await client.get(
        f"{API}/quotes/{quote['id']}/document.pdf",
        headers=h,
        params={"download": "false"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-disposition"].startswith("inline;")


@no_browser
async def test_an_unissued_quote_cannot_be_printed(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    record = await client.post(
        f"{API}/clients",
        headers=h,
        json={
            "name": f"Pdf Co {uuid.uuid4().hex[:8]}",
            "email": unique_email("pdf"),
            "residence_category_id": sample_catalogue["residence_citizen"],
        },
    )
    quote = (
        await client.post(
            f"{API}/quotes",
            headers=h,
            json={
                "client_id": record.json()["id"],
                "presentation_currency": "KES",
                "residence_category_id": sample_catalogue["residence_citizen"],
                "arrival_date": "2026-07-01",
                "departure_date": "2026-07-04",
                "pax_count": 25,
                "requested_meal_plan_id": sample_catalogue["meal_plan_fb"],
                "options": [
                    {
                        "accommodation_id": sample_catalogue["acc_sto_full_board"],
                        "is_recommended": True,
                    }
                ],
            },
        )
    ).json()
    resp = await client.get(f"{API}/quotes/{quote['id']}/document.pdf", headers=h)
    assert resp.status_code == 400
    assert "has not been issued" in resp.text


@no_browser
@ci_pdf_hang
async def test_printing_needs_only_quote_read(
    client, admin_tokens, sample_catalogue
):
    h = _h(admin_tokens)
    quote = await _issued_quote(client, h, sample_catalogue)
    email = unique_email("pdfviewer")
    await client.post(
        f"{API}/users",
        headers=h,
        json={"email": email, "password": "AgentPass123", "role_keys": ["viewer"]},
    )
    login = await client.post(
        f"{API}/auth/login", data={"username": email, "password": "AgentPass123"}
    )
    resp = await client.get(
        f"{API}/quotes/{quote['id']}/document.pdf", headers=_h(login.json())
    )
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"%PDF-")
