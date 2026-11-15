from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin
from app.modules.quotes.outcomes import effective_status

QUOTE_STATUSES = ("draft", "sent", "accepted", "declined", "expired")

REJECTION_SOURCES = ("engine", "manual")


class QuoteCounter(Base):

    __tablename__ = "quote_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Quote(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "quotes"

    quote_number: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    presentation_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    residence_category_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("residence_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    arrival_date: Mapped[date] = mapped_column(Date, nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)

    markup_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    tax_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)

    pax_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    contingency_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    requested_meal_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="RESTRICT"), nullable=True
    )
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    document_subtitle: Mapped[str | None] = mapped_column(String(240), nullable=True)
    selected_option_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "quote_options.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_quotes_selected_option_id",
        ),
        nullable=True,
    )
    selected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def effective_status(self) -> str:
        return effective_status(self.status, self.valid_until, today=date.today())

    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(
            "quote_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_quotes_current_version_id",
        ),
        nullable=True,
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    travellers: Mapped[list[QuoteTraveller]] = relationship(
        "QuoteTraveller",
        back_populates="quote",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteTraveller.id",
        foreign_keys="QuoteTraveller.quote_id",
    )
    legs: Mapped[list[QuoteLeg]] = relationship(
        "QuoteLeg",
        back_populates="quote",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteLeg.sequence",
        foreign_keys="QuoteLeg.quote_id",
    )
    transport: Mapped[list[QuoteTransport]] = relationship(
        "QuoteTransport",
        back_populates="quote",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteTransport.id",
        foreign_keys="QuoteTransport.quote_id",
    )
    options: Mapped[list[QuoteOption]] = relationship(
        "QuoteOption",
        back_populates="quote",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteOption.sort_order",
        foreign_keys="QuoteOption.quote_id",
    )
    transport_segments: Mapped[list[QuoteTransportSegment]] = relationship(
        "QuoteTransportSegment",
        back_populates="quote",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteTransportSegment.sequence",
        foreign_keys="QuoteTransportSegment.quote_id",
    )
    rejected_candidates: Mapped[list[QuoteRejectedCandidate]] = relationship(
        "QuoteRejectedCandidate",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteRejectedCandidate.sort_order",
    )
    cohorts: Mapped[list[QuoteCohort]] = relationship(
        "QuoteCohort",
        back_populates="quote",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteCohort.id",
        foreign_keys="QuoteCohort.quote_id",
    )


class QuoteCohort(UUIDPKMixin, Base):

    __tablename__ = "quote_cohorts"
    __table_args__ = (
        UniqueConstraint(
            "quote_id",
            "residence_category_id",
            "traveller_type",
            name="uq_quote_cohort",
        ),
        CheckConstraint("headcount > 0", name="ck_quote_cohort_headcount_positive"),
    )

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    residence_category_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("residence_categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    traveller_type: Mapped[str] = mapped_column(String(10), nullable=False)
    headcount: Mapped[int] = mapped_column(Integer, nullable=False)

    quote: Mapped[Quote] = relationship(
        "Quote", back_populates="cohorts", foreign_keys=[quote_id]
    )


class QuoteVersion(UUIDPKMixin, Base):

    __tablename__ = "quote_versions"
    __table_args__ = (UniqueConstraint("quote_id", "version_number", name="uq_quote_version_no"),)

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    internal_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gross_profit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gross_margin: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list[QuoteItem]] = relationship(
        "QuoteItem",
        back_populates="version",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    options: Mapped[list[QuoteVersionOption]] = relationship(
        "QuoteVersionOption",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteVersionOption.sort_order",
    )


class QuoteTraveller(UUIDPKMixin, Base):
    __tablename__ = "quote_travellers"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    traveller_type: Mapped[str] = mapped_column(String(10), nullable=False)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)

    quote: Mapped[Quote] = relationship(
        "Quote", back_populates="travellers", foreign_keys=[quote_id]
    )


class QuoteLeg(UUIDPKMixin, Base):
    __tablename__ = "quote_legs"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False
    )
    nights: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    check_in: Mapped[date | None] = mapped_column(Date, nullable=True)
    check_out: Mapped[date | None] = mapped_column(Date, nullable=True)

    quote: Mapped[Quote] = relationship("Quote", back_populates="legs", foreign_keys=[quote_id])
    accommodations: Mapped[list[QuoteAccommodation]] = relationship(
        "QuoteAccommodation",
        back_populates="leg",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    activities: Mapped[list[QuoteActivity]] = relationship(
        "QuoteActivity",
        back_populates="leg",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class QuoteAccommodation(UUIDPKMixin, Base):
    __tablename__ = "quote_accommodations"

    leg_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quote_legs.id", ondelete="CASCADE"), nullable=False
    )
    accommodation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accommodations.id", ondelete="RESTRICT"), nullable=False
    )
    room_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("room_types.id", ondelete="RESTRICT"), nullable=False
    )
    meal_plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="RESTRICT"), nullable=False
    )
    rooms: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    nights: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    leg: Mapped[QuoteLeg] = relationship("QuoteLeg", back_populates="accommodations")


class QuoteActivity(UUIDPKMixin, Base):
    __tablename__ = "quote_activities"

    leg_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quote_legs.id", ondelete="CASCADE"), nullable=False
    )
    activity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("activities.id", ondelete="RESTRICT"), nullable=False
    )
    day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adults: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    children: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    leg: Mapped[QuoteLeg] = relationship("QuoteLeg", back_populates="activities")


class QuoteTransport(UUIDPKMixin, Base):
    __tablename__ = "quote_transport"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    estimated_km: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0, nullable=False)
    days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    quote: Mapped[Quote] = relationship(
        "Quote", back_populates="transport", foreign_keys=[quote_id]
    )


class QuoteItem(UUIDPKMixin, Base):

    __tablename__ = "quote_items"

    version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quote_versions.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=1, nullable=False)
    source_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    internal_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    version: Mapped[QuoteVersion] = relationship("QuoteVersion", back_populates="items")


MEAL_PLAN_FALLBACK_ORDER = ("full_board", "half_board", "bed_and_breakfast")


class QuoteOption(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "quote_options"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), index=True,
        nullable=False,
    )
    accommodation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accommodations.id", ondelete="RESTRICT"), nullable=False
    )
    room_type_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("room_types.id", ondelete="RESTRICT"), nullable=True
    )
    meal_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="RESTRICT"), nullable=True
    )
    rooms_required: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meal_plan_fallback_from: Mapped[str | None] = mapped_column(String(30), nullable=True)
    is_comparable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    agent_cover_fee: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("0"), nullable=False
    )
    chef_fee_per_meal: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    manual_meal_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    quote: Mapped[Quote] = relationship(
        "Quote", back_populates="options", foreign_keys=[quote_id]
    )
    legs: Mapped[list[QuoteOptionLeg]] = relationship(
        "QuoteOptionLeg",
        back_populates="option",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="QuoteOptionLeg.sequence",
        foreign_keys="QuoteOptionLeg.quote_option_id",
    )


class QuoteOptionLeg(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "quote_option_legs"
    __table_args__ = (
        UniqueConstraint("quote_option_id", "sequence", name="uq_quote_option_leg_seq"),
        CheckConstraint("check_out > check_in", name="ck_quote_option_leg_dates"),
        CheckConstraint("sequence > 0", name="ck_quote_option_leg_sequence"),
    )

    quote_option_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("quote_options.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("destinations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    accommodation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("accommodations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    requested_meal_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="RESTRICT"), nullable=True
    )
    check_in: Mapped[date] = mapped_column(Date, nullable=False)
    check_out: Mapped[date] = mapped_column(Date, nullable=False)

    room_type_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("room_types.id", ondelete="RESTRICT"), nullable=True
    )
    meal_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="RESTRICT"), nullable=True
    )
    rooms_required: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meal_plan_fallback_from: Mapped[str | None] = mapped_column(String(30), nullable=True)

    option: Mapped[QuoteOption] = relationship(
        "QuoteOption", back_populates="legs", foreign_keys=[quote_option_id]
    )


class QuoteRejectedCandidate(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "quote_rejected_candidates"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), index=True,
        nullable=False,
    )
    accommodation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accommodations.id", ondelete="SET NULL"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source: Mapped[str] = mapped_column(
        String(10), default="engine", server_default=text("'engine'"), nullable=False
    )


class QuoteTransportSegment(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "quote_transport_segments"

    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="CASCADE"), index=True,
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    travel_class: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    destination_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=True
    )
    origin_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=True
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=True
    )
    vehicle_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    units: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    travel_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_vvip: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    quote: Mapped[Quote] = relationship(
        "Quote", back_populates="transport_segments", foreign_keys=[quote_id]
    )


class QuoteVersionOption(UUIDPKMixin, Base):

    __tablename__ = "quote_version_options"
    __table_args__ = (UniqueConstraint("version_id", "option_id", name="uq_version_option"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quote_versions.id", ondelete="CASCADE"), index=True,
        nullable=False,
    )
    option_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quote_options.id", ondelete="SET NULL"), nullable=True
    )
    accommodation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("accommodations.id", ondelete="SET NULL"), nullable=True
    )
    accommodation_name: Mapped[str] = mapped_column(String(200), nullable=False)
    meal_plan_label: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rooms_required: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cost_subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    contingency_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    profit_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    agent_cover_fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    supplier_paid_total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    retained_discount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    selling_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    per_person: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_comparable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
