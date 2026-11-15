from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CrewBase(BaseModel):
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=255)
    roles: list[str] | None = None
    licence_number: str | None = Field(default=None, max_length=60)
    licence_expires_on: date | None = None
    guide_licence_number: str | None = Field(default=None, max_length=60)
    guide_licence_expires_on: date | None = None
    languages: list[str] | None = None
    supplier_id: uuid.UUID | None = None
    notes: str | None = None


class CrewCreate(CrewBase):
    name: str = Field(min_length=1, max_length=200)
    roles: list[str] = Field(min_length=1)


class CrewUpdate(CrewBase):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class CrewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    phone: str | None
    email: str | None
    roles: list[str]
    licence_number: str | None
    licence_expires_on: date | None
    guide_licence_number: str | None
    guide_licence_expires_on: date | None
    languages: list[str]
    supplier_id: uuid.UUID | None
    is_active: bool
    notes: str | None
    created_at: datetime


class AssignmentCreate(BaseModel):

    vehicle_id: uuid.UUID | None = None
    crew_id: uuid.UUID | None = None
    role: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    notes: str | None = None
    override_reason: str | None = None


class AssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    booking_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    crew_id: uuid.UUID | None
    role: str
    starts_on: date
    ends_on: date
    notes: str | None
    override_reason: str | None
    assigned_by: uuid.UUID | None
    created_at: datetime


class ClashRead(BaseModel):
    code: str
    message: str
    reference: str = ""
    blocking: bool = True


class AssignmentMade(BaseModel):

    assignment: AssignmentRead
    advisories: list[ClashRead] = Field(default_factory=list)


class GapRead(BaseModel):
    code: str
    message: str
    days: int = 0


class RosterRead(BaseModel):

    vehicles: list[str] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    guides: list[str] = Field(default_factory=list)
    seats: int = 0


class ConcernRead(BaseModel):
    code: str
    message: str
    supplier: str = ""
    days: int = 0
    variance_pct: Decimal | None = None


class DepartureRead(BaseModel):

    booking_id: uuid.UUID
    reference: str
    arrival_date: date
    departure_date: date
    pax_count: int
    status: str
    roster: RosterRead
    gaps: list[GapRead] = Field(default_factory=list)
    supply: list[ConcernRead] = Field(default_factory=list)


class TripLogOpen(BaseModel):

    odometer_out_km: Decimal = Field(ge=0)
    started_on: date | None = None
    driver_id: uuid.UUID | None = None
    notes: str | None = None


class TripLogClose(BaseModel):
    odometer_in_km: Decimal = Field(ge=0)
    ended_on: date | None = None


class FuelFillCreate(BaseModel):

    litres: Decimal = Field(gt=0)
    amount: Decimal = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    bought_on: date | None = None
    station: str | None = Field(default=None, max_length=160)
    receipt_ref: str | None = Field(default=None, max_length=80)
    notes: str | None = None


class FuelFillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    litres: Decimal
    amount: Decimal
    currency: str
    bought_on: date
    station: str | None
    receipt_ref: str | None
    notes: str | None


class ActualRead(BaseModel):

    distance_km: Decimal | None = None
    litres: Decimal = Decimal(0)
    fuel_cost: Decimal = Decimal(0)
    currency: str = ""
    model_kmpl: Decimal | None = None
    actual_kmpl: Decimal | None = None
    model_litres: Decimal | None = None
    variance_pct: Decimal | None = None


class TripLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    assignment_id: uuid.UUID
    vehicle_id: uuid.UUID
    booking_id: uuid.UUID
    odometer_out_km: Decimal
    odometer_in_km: Decimal | None
    started_on: date
    ended_on: date | None
    driver_id: uuid.UUID | None
    notes: str | None
    distance_km: Decimal | None = None
    is_open: bool = False
    fills: list[FuelFillRead] = Field(default_factory=list)


class TripLogOpened(BaseModel):

    log: TripLogRead
    observations: list[str] = Field(default_factory=list)


class FindingRead(BaseModel):
    code: str
    message: str
    trips: int = 0
    model_kmpl: Decimal | None = None
    actual_kmpl: Decimal | None = None
    variance_pct: Decimal | None = None


class FleetTruthRead(BaseModel):

    vehicle: str
    trips: int = 0
    distance_km: Decimal = Decimal(0)
    litres: Decimal = Decimal(0)
    fuel_cost: Decimal = Decimal(0)
    currency: str = ""
    model_kmpl: Decimal | None = None
    actual_kmpl: Decimal | None = None
    findings: list[FindingRead] = Field(default_factory=list)


class SupplierBookingCreate(BaseModel):
    supplier_id: uuid.UUID
    service: str = Field(min_length=1, max_length=300)
    expected_amount: Decimal = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    check_in: date | None = None
    check_out: date | None = None
    confirm_by: date | None = None
    notes: str | None = None


class SupplierBookingMove(BaseModel):
    status: str
    their_reference: str | None = Field(default=None, max_length=120)
    reason: str | None = None
    on: date | None = None


class SupplierAmount(BaseModel):
    amount: Decimal = Field(ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    on: date | None = None


class SupplierBookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    booking_id: uuid.UUID
    supplier_id: uuid.UUID
    service: str
    status: str
    their_reference: str | None
    check_in: date | None
    check_out: date | None
    confirm_by: date | None
    expected_amount: Decimal
    invoiced_amount: Decimal | None
    settled_amount: Decimal | None
    currency: str
    requested_on: date | None
    confirmed_on: date | None
    settled_on: date | None
    cancel_reason: str | None
    notes: str | None
    created_at: datetime


class ExposureRead(BaseModel):

    expected: dict[str, Decimal] = Field(default_factory=dict)
    invoiced: dict[str, Decimal] = Field(default_factory=dict)
    settled: dict[str, Decimal] = Field(default_factory=dict)
    owed: dict[str, Decimal] = Field(default_factory=dict)
    suppliers: int = 0
    unconfirmed: int = 0
    all_confirmed: bool = False


class SupplyPositionRead(BaseModel):
    exposure: ExposureRead
    concerns: list[ConcernRead] = Field(default_factory=list)
