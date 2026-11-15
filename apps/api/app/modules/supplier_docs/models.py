from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

DOCUMENT_STATUSES = ("uploaded", "extracting", "extracted", "reviewed", "failed")

EXTRACTION_STATUSES = ("pending", "confirmed", "rejected")


class SupplierDocument(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "supplier_documents"

    accommodation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accommodations.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="uploaded", index=True, nullable=False
    )
    extraction_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    extractions: Mapped[list[SupplierDocumentExtraction]] = relationship(
        "SupplierDocumentExtraction",
        back_populates="document",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="SupplierDocumentExtraction.row_index",
    )


class SupplierDocumentExtraction(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "supplier_document_extractions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("supplier_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    row_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True, nullable=False
    )
    proposed: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accommodation_rates.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    document: Mapped[SupplierDocument] = relationship(
        "SupplierDocument", back_populates="extractions"
    )
