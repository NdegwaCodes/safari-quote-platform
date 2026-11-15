from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GrantCreate(BaseModel):
    label: str | None = Field(default=None, max_length=160)
    expires_on: date | None = None


class GrantRevoke(BaseModel):
    reason: str = Field(min_length=1)


class GrantRead(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    booking_id: uuid.UUID
    label: str | None
    expires_on: date
    revoked_at: datetime | None
    revoke_reason: str | None
    last_seen_at: datetime | None
    view_count: int
    created_at: datetime


class GrantIssued(GrantRead):

    token: str
    url: str


class MovementRead(BaseModel):
    label: str
    minutes: int | None = None


class DayRead(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    number: int
    on: date | None = Field(default=None, alias="date")
    destination: str = ""
    property_name: str = ""
    board: str = ""
    movements: list[MovementRead] = Field(default_factory=list)
    excursions: list[str] = Field(default_factory=list)
    is_arrival: bool = False
    is_departure: bool = False
    has_night: bool = True


class StayRead(BaseModel):
    sequence: int
    destination: str = ""
    property_name: str = ""
    room_type: str = ""
    board: str = ""
    rooms: int = 0
    nights: int = 0


class TripRead(BaseModel):

    reference: str
    status: str
    arrival_date: date | None = None
    departure_date: date | None = None
    pax_count: int = 0
    total: Decimal
    currency: str
    property_name: str = ""
    room_type: str = ""
    board: str = ""
    nights: int = 0
    description: str | None = None
    stays: list[StayRead] = Field(default_factory=list)
    days: list[DayRead] = Field(default_factory=list)
    included: list[str] = Field(default_factory=list)


class InstalmentRead(BaseModel):
    label: str
    due_on: date
    amount: Decimal
    currency: str


class PaymentRead(BaseModel):

    amount: Decimal
    currency: str
    paid_on: date
    method: str
    reference: str | None = None


class StatementRead(BaseModel):

    reference: str
    currency: str
    total: Decimal
    paid: Decimal
    balance: Decimal
    overpaid: Decimal = Decimal(0)
    is_settled: bool = False
    schedule: list[InstalmentRead] = Field(default_factory=list)
    payments: list[PaymentRead] = Field(default_factory=list)
    overdue: list[InstalmentRead] = Field(default_factory=list)
    next_due: InstalmentRead | None = None
