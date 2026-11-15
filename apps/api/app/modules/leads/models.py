from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

COMMON_SOURCES = (
    "website",
    "referral",
    "repeat_client",
    "walk_in",
    "phone",
    "email",
    "agent",
    "social",
    "other",
)


class LeadStage(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "lead_stages"
    __table_args__ = (
        UniqueConstraint("key", name="uq_lead_stage_key"),
        Index("ix_lead_stage_order", "sort_order"),
    )

    key: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    is_won: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    is_lost: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    @property
    def is_terminal(self) -> bool:
        return self.is_won or self.is_lost


class Lead(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_lead_stage_owner", "stage_id", "owner_id"),
        Index("ix_lead_next_action", "next_action_on"),
    )

    source: Mapped[str] = mapped_column(String(40), default="other", nullable=False)
    source_detail: Mapped[str | None] = mapped_column(String(160), nullable=True)

    client_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    contact_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255), index=True, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    stage_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("lead_stages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    stage_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    destination_interest: Mapped[str | None] = mapped_column(String(200), nullable=True)
    travel_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    travel_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    pax_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    budget_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)

    next_action_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_action_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_contact_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_inbound_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    lost_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    stage: Mapped[LeadStage] = relationship("LeadStage", lazy="selectin")
    events: Mapped[list[LeadStageEvent]] = relationship(
        "LeadStageEvent",
        back_populates="lead",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="LeadStageEvent.at",
    )


class LeadStageEvent(UUIDPKMixin, Base):

    __tablename__ = "lead_stage_events"
    __table_args__ = (Index("ix_lead_stage_event_lead", "lead_id", "at"),)

    lead_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    from_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lead_stages.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_stage_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lead_stages.id", ondelete="RESTRICT"),
        nullable=False,
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    lead: Mapped[Lead] = relationship("Lead", back_populates="events")
