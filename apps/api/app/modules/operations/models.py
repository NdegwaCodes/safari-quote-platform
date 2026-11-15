from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin


class CrewMember(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "crew"
    __table_args__ = (
        Index("ix_crew_active", "is_active"),
    )

    name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    roles: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )

    licence_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    licence_expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    guide_licence_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    guide_licence_expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    languages: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)

    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("suppliers.id", ondelete="SET NULL"),
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class TripAssignment(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "trip_assignments"
    __table_args__ = (
        CheckConstraint(
            "(vehicle_id is null) <> (crew_id is null)",
            name="ck_assignment_one_subject",
        ),
        CheckConstraint("ends_on >= starts_on", name="ck_assignment_window"),
        CheckConstraint(
            "role in ('driver', 'guide', 'driver_guide', 'vehicle')",
            name="ck_assignment_role",
        ),
        Index("ix_assignment_booking", "booking_id"),
        Index("ix_assignment_vehicle_dates", "vehicle_id", "starts_on", "ends_on"),
        Index("ix_assignment_crew_dates", "crew_id", "starts_on", "ends_on"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=True,
    )
    crew_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("crew.id", ondelete="RESTRICT"), nullable=True
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)

    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


VEHICLE = "vehicle"


class TripLog(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "trip_logs"
    __table_args__ = (
        UniqueConstraint("assignment_id", name="uq_trip_log_assignment"),
        CheckConstraint(
            "odometer_in_km is null or odometer_in_km >= odometer_out_km",
            name="ck_trip_log_odometer",
        ),
        CheckConstraint("odometer_out_km >= 0", name="ck_trip_log_out_positive"),
        Index("ix_trip_log_vehicle", "vehicle_id", "started_on"),
    )

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("trip_assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    booking_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
    )

    odometer_out_km: Mapped[Decimal] = mapped_column(Numeric(12, 1), nullable=False)
    odometer_in_km: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 1), nullable=True
    )
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    ended_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    driver_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("crew.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    fills: Mapped[list[FuelFill]] = relationship(
        "FuelFill",
        back_populates="log",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FuelFill.bought_on",
    )

    @property
    def distance_km(self) -> Decimal | None:
        if self.odometer_in_km is None:
            return None
        return self.odometer_in_km - self.odometer_out_km

    @property
    def is_open(self) -> bool:
        return self.odometer_in_km is None


class FuelFill(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "fuel_fills"
    __table_args__ = (
        CheckConstraint("litres > 0", name="ck_fuel_fill_litres"),
        CheckConstraint("amount > 0", name="ck_fuel_fill_amount"),
        Index("ix_fuel_fill_log", "trip_log_id"),
    )

    trip_log_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("trip_logs.id", ondelete="CASCADE"),
        nullable=False,
    )
    litres: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    bought_on: Mapped[date] = mapped_column(Date, nullable=False)
    station: Mapped[str | None] = mapped_column(String(160), nullable=True)
    receipt_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    log: Mapped[TripLog] = relationship("TripLog", back_populates="fills")


class SupplierBooking(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "supplier_bookings"
    __table_args__ = (
        CheckConstraint(
            "status in ('to_request', 'requested', 'confirmed', 'cancelled')",
            name="ck_supplier_booking_status",
        ),
        CheckConstraint(
            "expected_amount >= 0", name="ck_supplier_booking_expected"
        ),
        CheckConstraint(
            "invoiced_amount is null or invoiced_amount >= 0",
            name="ck_supplier_booking_invoiced",
        ),
        CheckConstraint(
            "settled_amount is null or settled_amount >= 0",
            name="ck_supplier_booking_settled",
        ),
        CheckConstraint(
            "check_out is null or check_in is null or check_out >= check_in",
            name="ck_supplier_booking_dates",
        ),
        Index("ix_supplier_booking_booking", "booking_id"),
        Index("ix_supplier_booking_supplier", "supplier_id", "status"),
    )

    booking_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    service: Mapped[str] = mapped_column(String(300), nullable=False)

    status: Mapped[str] = mapped_column(String(20), default="to_request", nullable=False)
    their_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)

    check_in: Mapped[date | None] = mapped_column(Date, nullable=True)
    check_out: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirm_by: Mapped[date | None] = mapped_column(Date, nullable=True)

    expected_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=0, nullable=False
    )
    invoiced_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    settled_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)

    requested_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    confirmed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    settled_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
