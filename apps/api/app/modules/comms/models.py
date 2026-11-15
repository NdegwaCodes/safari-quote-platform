from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

LEAD = "lead"
CLIENT = "client"
QUOTE = "quote"
BOOKING = "booking"
SUBJECTS = (LEAD, CLIENT, QUOTE, BOOKING)


class Communication(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "communications"
    __table_args__ = (
        CheckConstraint(
            "subject in ('lead', 'client', 'quote', 'booking')",
            name="ck_communication_subject",
        ),
        CheckConstraint(
            "direction in ('inbound', 'outbound', 'internal')",
            name="ck_communication_direction",
        ),
        CheckConstraint(
            "duration_minutes is null or (duration_minutes > 0 and reached is not false)",
            name="ck_communication_duration",
        ),
        Index("ix_communication_subject", "subject", "subject_id", "occurred_at"),
    )

    subject: Mapped[str] = mapped_column(String(20), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    subject_line: Mapped[str | None] = mapped_column(String(200), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    reached: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)

    logged_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    amended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    amended_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    voided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def is_voided(self) -> bool:
        return self.voided_at is not None
