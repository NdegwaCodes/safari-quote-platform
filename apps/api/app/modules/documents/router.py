from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.modules.documents.schemas import DocumentConfigRead, DocumentConfigUpdate
from app.modules.documents.service import (
    DocumentConfigService,
    QuotationDocumentService,
)
from app.modules.users.models import User

router = APIRouter(tags=["documents"])


@router.get("/document-config", response_model=DocumentConfigRead)
async def get_document_config(
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("settings:read")),
):
    return await DocumentConfigService(db).get()


@router.patch("/document-config", response_model=DocumentConfigRead)
async def update_document_config(
    body: DocumentConfigUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission("settings:update")),
):
    patch = body.model_dump(exclude_unset=True)
    return await DocumentConfigService(db).update(patch, updated_by=actor.id)


@router.get(
    "/quotes/{quote_id}/document.html",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {}}}},
)
async def render_quotation_html(
    quote_id: uuid.UUID,
    version: int | None = Query(
        default=None,
        ge=1,
        description="Version number to render. Defaults to the latest issued one.",
    ),
    inline_assets: bool = Query(
        default=True,
        description=(
            "Embed the photographs in the document. False links them instead, "
            "for a preview whose fetcher can authenticate."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("quote:read")),
):
    html = await QuotationDocumentService(db).render_html(
        quote_id, version_number=version, inline_assets=inline_assets
    )
    return HTMLResponse(content=html)


@router.get(
    "/quotes/{quote_id}/worksheet.html",
    response_class=HTMLResponse,
    responses={200: {"content": {"text/html": {}}}},
)
async def render_costing_worksheet(
    quote_id: uuid.UUID,
    version: int | None = Query(
        default=None,
        ge=1,
        description="Version number to explain. Defaults to the latest issued one.",
    ),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("quote:read_cost")),
):
    html = await QuotationDocumentService(db).render_worksheet_html(
        quote_id, version_number=version
    )
    return HTMLResponse(content=html)


@router.get(
    "/quotes/{quote_id}/document.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def render_quotation_pdf(
    quote_id: uuid.UUID,
    version: int | None = Query(
        default=None,
        ge=1,
        description="Version number to print. Defaults to the latest issued one.",
    ),
    download: bool = Query(
        default=True,
        description="Send as an attachment. False renders inline in the browser.",
    ),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission("quote:read")),
):
    pdf, filename = await QuotationDocumentService(db).render_pdf(
        quote_id, version_number=version
    )
    disposition = "attachment" if download else "inline"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )
