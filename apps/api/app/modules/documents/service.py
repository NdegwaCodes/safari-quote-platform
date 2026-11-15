from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.integrations.pdf_render import PdfRenderError, PdfRenderProvider
from app.modules.documents.config import DOCUMENT_SETTINGS_KEY, DocumentConfig
from app.modules.documents.fonts import face_css
from app.modules.documents.pdf import default_renderer
from app.modules.documents.viewmodel import QuotationView, QuotationViewBuilder
from app.modules.documents.worksheet import Worksheet, WorksheetBuilder
from app.modules.quotes.models import Quote, QuoteVersion
from app.modules.settings.models import AppSetting

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


@dataclass(frozen=True)
class PageGeometry:

    css_size: str
    width: str
    height: str


PAGE_SIZES: dict[str, PageGeometry] = {
    "A4": PageGeometry(css_size="A4", width="210mm", height="297mm"),
    "Letter": PageGeometry(css_size="Letter", width="215.9mm", height="279.4mm"),
}


class DocumentConfigService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _row(self) -> AppSetting | None:
        stmt = select(AppSetting).where(AppSetting.key == DOCUMENT_SETTINGS_KEY)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get(self) -> DocumentConfig:
        row = await self._row()
        if row is None:
            return DocumentConfig()
        return DocumentConfig.model_validate(row.value)

    async def update(
        self, patch: dict[str, Any], *, updated_by: Any | None = None
    ) -> DocumentConfig:
        current = await self.get()
        merged = DocumentConfig.model_validate({**current.model_dump(), **patch})
        payload = merged.model_dump(mode="json")
        row = await self._row()
        if row is None:
            self.db.add(
                AppSetting(
                    key=DOCUMENT_SETTINGS_KEY, value=payload, updated_by=updated_by
                )
            )
        else:
            row.value = payload
            row.updated_by = updated_by
        try:
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            raise ConflictError("Could not save the document configuration.") from exc
        return merged


def environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(
            enabled_extensions=("html", "j2"), default_for_string=True
        ),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


class QuotationDocumentService:
    def __init__(self, db: AsyncSession, renderer: PdfRenderProvider | None = None):
        self.db = db
        self.renderer: PdfRenderProvider = renderer or default_renderer()

    async def view(
        self,
        quote_id: uuid.UUID,
        *,
        version_number: int | None = None,
        inline_assets: bool = True,
    ) -> QuotationView:
        quote, version = await self._resolve(quote_id, version_number)
        config = await DocumentConfigService(self.db).get()
        builder = QuotationViewBuilder(self.db, inline_assets=inline_assets)
        return await builder.build(quote, version, config)

    async def render_html(
        self,
        quote_id: uuid.UUID,
        *,
        version_number: int | None = None,
        inline_assets: bool = True,
    ) -> str:
        view = await self.view(
            quote_id, version_number=version_number, inline_assets=inline_assets
        )
        page = PAGE_SIZES.get(view.config.page_size, PAGE_SIZES["A4"])
        template = environment().get_template("quotation.html.j2")
        return template.render(view=view, page=page, fonts_css=face_css())

    async def worksheet(
        self, quote_id: uuid.UUID, *, version_number: int | None = None
    ) -> Worksheet:
        quote, version = await self._resolve(quote_id, version_number)
        return await WorksheetBuilder(self.db).build(quote, version)

    async def render_worksheet_html(
        self, quote_id: uuid.UUID, *, version_number: int | None = None
    ) -> str:
        view = await self.worksheet(quote_id, version_number=version_number)
        template = environment().get_template("worksheet.html.j2")
        return template.render(view=view)

    async def render_pdf(
        self, quote_id: uuid.UUID, *, version_number: int | None = None
    ) -> tuple[bytes, str]:
        if not self.renderer.is_available():
            raise AppError(
                "No PDF renderer is available on this host, so the document can "
                "only be produced as HTML. Install a Chromium-family browser or "
                "set PDF_BROWSER_PATH."
            )
        quote, version = await self._resolve(quote_id, version_number)
        html = await self.render_html(
            quote_id, version_number=version.version_number, inline_assets=True
        )
        try:
            pdf = await self.renderer.render(
                html, timeout_seconds=settings.PDF_RENDER_TIMEOUT_SECONDS
            )
        except PdfRenderError as exc:
            raise AppError(f"The document could not be printed: {exc}") from exc
        return pdf, self.filename(quote.quote_number, version.version_number)

    @staticmethod
    def filename(quote_number: str, version_number: int) -> str:
        return f"{quote_number}-v{version_number}.pdf"

    async def _resolve(
        self, quote_id: uuid.UUID, version_number: int | None
    ) -> tuple[Quote, QuoteVersion]:
        quote = (
            await self.db.execute(select(Quote).where(Quote.id == quote_id))
        ).scalar_one_or_none()
        if quote is None:
            raise NotFoundError("Quote not found.")

        stmt = select(QuoteVersion).where(QuoteVersion.quote_id == quote_id)
        if version_number is not None:
            stmt = stmt.where(QuoteVersion.version_number == version_number)
        else:
            stmt = stmt.order_by(QuoteVersion.version_number.desc())
        version = (await self.db.execute(stmt.limit(1))).scalar_one_or_none()
        if version is None:
            raise AppError(
                "This quote has not been issued yet, so there is no document to "
                "render. Issue it first — that is what freezes the figures the "
                "document prints."
            )
        return quote, version
