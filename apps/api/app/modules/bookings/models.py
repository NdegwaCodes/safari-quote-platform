from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

PROVISIONAL = "provisional"
CONFIRMED = "confirmed"
CANCELLED = "cancelled"
COMPLETED = "completed"
BOOKING_STATUSES = (PROVISIONAL, CONFIRMED, CANCELLED, COMPLETED)

ACTIVE_STATUSES = (PROVISIONAL, CONFIRMED)

PAYMENT_METHODS = ("mpesa", "bank_transfer", "card", "cash", "cheque", "other")


class BookingCounter(Base):

    __tablename__ = "booking_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Booking(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(
            "status in ('provisional', 'confirmed', 'cancelled', 'completed')",
            name="ck_booking_status",
        ),
        CheckConstraint("total_amount >= 0", name="ck_booking_total_positive"),
        CheckConstraint("departure_date > arrival_date", name="ck_booking_dates"),
        Index("ix_booking_quote", "quote_id"),
        Index("ix_booking_status_dates", "status", "arrival_date"),
    )

    reference: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=False
    )
    quote_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quotes.id", ondelete="RESTRICT"), nullable=False
    )
    quote_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("quote_versions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    option_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("quote_options.id", ondelete="SET NULL"),
        nullable=True,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default=PROVISIONAL, index=True, nullable=False
    )

    arrival_date: Mapped[date] = mapped_column(Date, nullable=False)
    departure_date: Mapped[date] = mapped_column(Date, nullable=False)
    pax_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retained_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cancellation_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cancellation_notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_exclusive_use: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    instalments: Mapped[list[BookingInstalment]] = relationship(
        "BookingInstalment",
        back_populates="booking",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="BookingInstalment.sort_order",
    )
    payments: Mapped[list[Payment]] = relationship(
        "Payment",
        back_populates="booking",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="Payment.paid_on",
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


class BookingInstalment(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "booking_instalments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_instalment_amount_positive"),
        Index("ix_instalment_due", "due_on"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    booking: Mapped[Booking] = relationship("Booking", back_populates="instalments")


class Payment(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_amount_positive"),
        Index("ix_payment_booking", "booking_id", "paid_on"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(20), default="other", nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), index=True, nullable=True)
    instalment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("booking_instalments.id", ondelete="SET NULL"),
        nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    booking: Mapped[Booking] = relationship("Booking", back_populates="payments")
