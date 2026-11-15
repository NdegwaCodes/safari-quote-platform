from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BookingCreate(BaseModel):

    notes: str | None = Field(default=None, max_length=2000)
    is_exclusive_use: bool = False


class InstalmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    due_on: date
    amount: Decimal
    currency: str
    sort_order: int


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    amount: Decimal
    currency: str
    paid_on: date
    method: str
    reference: str | None
    instalment_id: uuid.UUID | None
    notes: str | None
    recorded_by: uuid.UUID | None
    created_at: datetime


class PaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0)
    paid_on: date
    method: str = Field(default="other", max_length=20)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    reference: str | None = Field(default=None, max_length=120)
    instalment_id: uuid.UUID | None = None
    notes: str | None = None


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    reference: str
    quote_id: uuid.UUID
    quote_version_id: uuid.UUID
    option_id: uuid.UUID | None
    client_id: uuid.UUID
    status: str
    arrival_date: date
    departure_date: date
    pax_count: int
    total_amount: Decimal
    currency: str
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    retained_amount: Decimal | None
    cancellation_band: str | None
    cancellation_notice_days: int | None
    is_exclusive_use: bool
    completed_at: datetime | None
    notes: str | None
    created_at: datetime
    instalments: list[InstalmentRead] = Field(default_factory=list)
    payments: list[PaymentRead] = Field(default_factory=list)


class ScheduleLineRead(BaseModel):

    label: str
    due_on: date
    amount: Decimal
    currency: str


class OwedRead(BaseModel):

    total: Decimal
    paid: Decimal
    balance: Decimal
    overpaid: Decimal
    currency: str
    is_settled: bool
    overdue: list[ScheduleLineRead] = Field(default_factory=list)
    next_due: ScheduleLineRead | None = None


class BookingDueRead(BaseModel):

    booking: BookingRead
    owed: OwedRead


class CancelBooking(BaseModel):

    reason: str = Field(min_length=1, max_length=2000)


class CancellationPreviewRead(BaseModel):

    notice_days: int
    band: str
    is_peak: bool
    is_group: bool
    retained_pct: Decimal
    retained_amount: Decimal
    currency: str
    peak_label: str = ""


class CancellationSettlementRead(BaseModel):

    retained_amount: Decimal
    paid_amount: Decimal
    refund_due: Decimal
    still_owed: Decimal
    currency: str
