from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

PENDING = "pending"
COMPLETED = "completed"
FAILED = "failed"
MPESA_TRANSACTION_STATUSES = (PENDING, COMPLETED, FAILED)


class MpesaTransaction(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "mpesa_transactions"
    __table_args__ = (
        CheckConstraint(
            "status in ('pending', 'completed', 'failed')",
            name="ck_mpesa_transaction_status",
        ),
        CheckConstraint("amount > 0", name="ck_mpesa_transaction_amount_positive"),
        Index("ix_mpesa_transaction_booking", "booking_id"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
    )
    instalment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("booking_instalments.id", ondelete="SET NULL"),
        nullable=True,
    )
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
    )
    phone_number: Mapped[str] = mapped_column(String(12), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=PENDING, index=True, nullable=False
    )
    merchant_request_id: Mapped[str] = mapped_column(String(60), nullable=False)
    checkout_request_id: Mapped[str] = mapped_column(
        String(60), unique=True, index=True, nullable=False
    )
    result_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    mpesa_receipt_number: Mapped[str | None] = mapped_column(
        String(30), index=True, nullable=True
    )
    callback_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    booking = relationship("Booking")
    payment = relationship("Payment")


__all__ = [
    "COMPLETED",
    "FAILED",
    "MPESA_TRANSACTION_STATUSES",
    "PENDING",
    "MpesaTransaction",
]
