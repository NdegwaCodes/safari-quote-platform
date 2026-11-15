from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base, TimestampMixin, UUIDPKMixin

TRANSPORT_MODES = ("road", "rail")

COST_BASES = ("per_person", "per_vehicle", "per_leg")


class DestinationTransportMode(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "destination_transport_modes"
    __table_args__ = (
        UniqueConstraint(
            "destination_id",
            "mode",
            "travel_class",
            "effective_from",
            name="uq_destination_transport_mode_period",
        ),
    )

    destination_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("destinations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    travel_class: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cost_basis: Mapped[str] = mapped_column(String(20), default="per_person", nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_inclusive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    vat_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("16"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class TransferRate(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "transfer_rates"
    __table_args__ = (
        UniqueConstraint(
            "destination_id",
            "vehicle_type",
            "route_label",
            "effective_from",
            name="uq_transfer_rate_period",
        ),
    )

    destination_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("destinations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    vehicle_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    passenger_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    route_label: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    price_per_leg: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    vat_inclusive: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    vat_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("16"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Route(UUIDPKMixin, TimestampMixin, Base):

    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint(
            "origin_id",
            "destination_id",
            "effective_from",
            name="uq_route_period",
        ),
        CheckConstraint("distance_km > 0", name="ck_route_distance_positive"),
        CheckConstraint(
            "drive_time_minutes > 0", name="ck_route_drive_time_positive"
        ),
        CheckConstraint("origin_id <> destination_id", name="ck_route_endpoints_differ"),
    )

    origin_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("destinations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("destinations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    distance_km: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    drive_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    required_vehicle_types: Mapped[list[str]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
