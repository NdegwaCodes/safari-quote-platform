from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.modules.bookings.models import ACTIVE_STATUSES, Booking
from app.modules.operations.actuals import (
    DEFAULT_TOLERANCE_PCT,
    Actual,
    Fill,
    FleetTruth,
    LogRefused,
    Odometer,
    audit,
    check_fill,
    check_reading,
    measure,
)
from app.modules.operations.models import (
    VEHICLE,
    CrewMember,
    FuelFill,
    SupplierBooking,
    TripAssignment,
    TripLog,
)
from app.modules.operations.roster import (
    CREW_ROLES,
    DRIVES,
    GUIDES,
    AssignmentRefused,
    Clash,
    Crew,
    Fleet,
    Gap,
    Held,
    Roster,
    Window,
    check_crew,
    check_ready,
    check_vehicle,
    clashes,
    sort_gaps,
)
from app.modules.operations.supply import (
    CANCELLED,
    CONFIRMED,
    DEFAULT_CONFIRM_BY_DAYS,
    REQUESTED,
    TO_REQUEST,
    Committed,
    Concern,
    Exposure,
    SupplyRefused,
    check_invoices,
    check_supply,
    check_transition,
    exposure,
    normalise_status,
    unsettled,
)
from app.modules.suppliers.models import Supplier
from app.modules.vehicles.models import Vehicle


def normalise_roles(values: Sequence[str] | None) -> list[str]:
    cleaned = []
    for value in values or []:
        role = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
        if role not in CREW_ROLES:
            raise AppError(
                f"'{value}' is not something somebody does on a trip. Say "
                f"{', '.join(CREW_ROLES)}."
            )
        if role not in cleaned:
            cleaned.append(role)
    if not cleaned:
        raise AppError(
            "Say what this person does — driver, guide, or driver_guide. "
            "Somebody with no role cannot be put on a trip at all."
        )
    return cleaned


class CrewService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> CrewMember:
        data = dict(data)
        data["roles"] = normalise_roles(data.get("roles"))
        row = CrewMember(**data)
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def get(self, crew_id: uuid.UUID) -> CrewMember:
        row = await self.db.get(CrewMember, crew_id)
        if row is None:
            raise NotFoundError("Crew member not found.")
        return row

    async def list(
        self, *, role: str | None = None, active_only: bool = True
    ) -> list[CrewMember]:
        stmt = select(CrewMember).order_by(CrewMember.name)
        if active_only:
            stmt = stmt.where(CrewMember.is_active.is_(True))
        rows = list((await self.db.execute(stmt)).scalars().all())
        if role:
            wanted = DRIVES if role == "driver" else GUIDES if role == "guide" else (role,)
            rows = [one for one in rows if set(one.roles) & set(wanted)]
        return rows

    async def update(self, crew_id: uuid.UUID, data: dict) -> CrewMember:
        row = await self.get(crew_id)
        if "roles" in data and data["roles"] is not None:
            data["roles"] = normalise_roles(data["roles"])
        for field, value in data.items():
            setattr(row, field, value)
        await self.db.commit()
        await self.db.refresh(row)
        return row


class AssignmentService:
    def __init__(self, db: AsyncSession):
        self.db = db


    async def assign(
        self,
        booking_id: uuid.UUID,
        *,
        vehicle_id: uuid.UUID | None = None,
        crew_id: uuid.UUID | None = None,
        role: str | None = None,
        starts_on: date | None = None,
        ends_on: date | None = None,
        notes: str | None = None,
        override_reason: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> tuple[TripAssignment, list[Clash]]:
        booking = await self.db.get(Booking, booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.")
        if booking.status not in ACTIVE_STATUSES:
            raise AppError(
                f"Booking {booking.reference} is {booking.status}, so there is "
                f"no trip to crew. Cancelling a booking releases what it held."
            )
        if (vehicle_id is None) == (crew_id is None):
            raise AppError(
                "An assignment is one vehicle or one person, not both and not "
                "neither."
            )

        window = Window(
            starts_on=starts_on or booking.arrival_date,
            ends_on=ends_on or booking.departure_date,
        )

        try:
            if vehicle_id is not None:
                found = await self._vehicle(vehicle_id)
                check_vehicle(found)
                subject, kind = found.name, VEHICLE
            else:
                assert crew_id is not None
                member = await self.get_crew(crew_id)
                kind = (role or "").strip().lower() or _default_role(member)
                check_crew(_crew(member), kind, window)
                subject = member.name
        except AssignmentRefused as exc:
            raise AppError(str(exc)) from exc

        held = await self._held(vehicle_id=vehicle_id, crew_id=crew_id)
        found_clashes = clashes(window, held, subject=subject)
        blocking = [one for one in found_clashes if one.blocking]
        if blocking and not (override_reason or "").strip():
            raise AppError(
                blocking[0].message
                + " Assign something else, or say why you are overriding it."
            )

        row = TripAssignment(
            booking_id=booking.id,
            vehicle_id=vehicle_id,
            crew_id=crew_id,
            role=kind,
            starts_on=window.starts_on,
            ends_on=window.ends_on,
            notes=notes,
            override_reason=(override_reason or "").strip() or None,
            assigned_by=actor_id,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row, [one for one in found_clashes if not one.blocking]

    async def release(self, assignment_id: uuid.UUID) -> None:
        row = await self.db.get(TripAssignment, assignment_id)
        if row is None:
            raise NotFoundError("Assignment not found.")
        await self.db.delete(row)
        await self.db.commit()

    async def for_booking(self, booking_id: uuid.UUID) -> list[TripAssignment]:
        return list(
            (
                await self.db.execute(
                    select(TripAssignment)
                    .where(TripAssignment.booking_id == booking_id)
                    .order_by(TripAssignment.starts_on, TripAssignment.role)
                )
            )
            .scalars()
            .all()
        )


    async def readiness(
        self, booking_id: uuid.UUID, *, today: date | None = None
    ) -> list[Gap]:
        booking = await self.db.get(Booking, booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.")
        rosters = await self._rosters([booking])
        return sort_gaps(
            check_ready(rosters[booking.id], today=today or date.today())
        )

    async def departures(
        self, *, days: int = 14, today: date | None = None
    ) -> list[tuple[Booking, Roster, list[Gap]]]:
        when = today or date.today()
        horizon = when.toordinal() + max(days, 0)
        bookings = list(
            (
                await self.db.execute(
                    select(Booking)
                    .where(
                        Booking.status.in_(ACTIVE_STATUSES),
                        Booking.arrival_date >= when,
                        Booking.arrival_date <= date.fromordinal(horizon),
                    )
                    .order_by(Booking.arrival_date)
                )
            )
            .scalars()
            .all()
        )
        rosters = await self._rosters(bookings)
        out = []
        for booking in bookings:
            roster = rosters[booking.id]
            out.append(
                (booking, roster, sort_gaps(check_ready(roster, today=when)))
            )
        return out

    async def diary(
        self,
        *,
        starts_on: date,
        ends_on: date,
        vehicle_id: uuid.UUID | None = None,
        crew_id: uuid.UUID | None = None,
    ) -> list[TripAssignment]:
        window = Window(starts_on=starts_on, ends_on=ends_on)
        stmt = select(TripAssignment).where(
            TripAssignment.starts_on <= window.ends_on,
            TripAssignment.ends_on >= window.starts_on,
        )
        if vehicle_id is not None:
            stmt = stmt.where(TripAssignment.vehicle_id == vehicle_id)
        if crew_id is not None:
            stmt = stmt.where(TripAssignment.crew_id == crew_id)
        return list(
            (
                await self.db.execute(
                    stmt.order_by(TripAssignment.starts_on, TripAssignment.role)
                )
            )
            .scalars()
            .all()
        )


    async def get_crew(self, crew_id: uuid.UUID) -> CrewMember:
        row = await self.db.get(CrewMember, crew_id)
        if row is None:
            raise NotFoundError("Crew member not found.")
        return row

    async def _vehicle(self, vehicle_id: uuid.UUID) -> Fleet:
        row = await self.db.get(Vehicle, vehicle_id)
        if row is None:
            raise NotFoundError("Vehicle not found.")
        return Fleet(
            name=row.name,
            vehicle_type=row.vehicle_type,
            passenger_capacity=row.passenger_capacity,
            is_active=row.is_active,
        )

    async def _held(
        self, *, vehicle_id: uuid.UUID | None, crew_id: uuid.UUID | None
    ) -> list[Held]:
        stmt = (
            select(TripAssignment, Booking.reference)
            .join(Booking, Booking.id == TripAssignment.booking_id)
            .where(Booking.status.in_(ACTIVE_STATUSES))
        )
        if vehicle_id is not None:
            stmt = stmt.where(TripAssignment.vehicle_id == vehicle_id)
        else:
            stmt = stmt.where(TripAssignment.crew_id == crew_id)
        return [
            Held(
                window=Window(starts_on=row.starts_on, ends_on=row.ends_on),
                reference=reference,
                booking_id=row.booking_id,
            )
            for row, reference in (await self.db.execute(stmt)).all()
        ]

    async def _rosters(
        self, bookings: Sequence[Booking]
    ) -> dict[uuid.UUID, Roster]:
        ids = [booking.id for booking in bookings]
        out = {
            booking.id: Roster(
                reference=booking.reference,
                departs_on=booking.arrival_date,
                pax_count=booking.pax_count,
            )
            for booking in bookings
        }
        if not ids:
            return out

        rows = list(
            (
                await self.db.execute(
                    select(TripAssignment).where(
                        TripAssignment.booking_id.in_(ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return out

        vehicles = {
            row.id: row
            for row in (
                await self.db.execute(
                    select(Vehicle).where(
                        Vehicle.id.in_(
                            [one.vehicle_id for one in rows if one.vehicle_id]
                        )
                    )
                )
            )
            .scalars()
            .all()
        }
        crew = {
            row.id: row
            for row in (
                await self.db.execute(
                    select(CrewMember).where(
                        CrewMember.id.in_(
                            [one.crew_id for one in rows if one.crew_id]
                        )
                    )
                )
            )
            .scalars()
            .all()
        }

        for row in rows:
            roster = out.get(row.booking_id)
            if roster is None:
                continue
            if row.vehicle_id is not None:
                found = vehicles.get(row.vehicle_id)
                if found is not None:
                    roster.vehicles.append(
                        Fleet(
                            name=found.name,
                            vehicle_type=found.vehicle_type,
                            passenger_capacity=found.passenger_capacity,
                            is_active=found.is_active,
                        )
                    )
            elif row.crew_id is not None:
                member = crew.get(row.crew_id)
                if member is None:
                    continue
                if row.role in DRIVES:
                    roster.drivers.append(_crew(member))
                if row.role in GUIDES:
                    roster.guides.append(_crew(member))
        return out


class TripLogService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def open(
        self,
        assignment_id: uuid.UUID,
        *,
        odometer_out_km: Decimal,
        started_on: date | None = None,
        driver_id: uuid.UUID | None = None,
        notes: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> tuple[TripLog, list[str]]:
        assignment = await self.db.get(TripAssignment, assignment_id)
        if assignment is None:
            raise NotFoundError("Assignment not found.")
        if assignment.vehicle_id is None:
            raise AppError(
                "A trip log belongs to a vehicle. This assignment is a person, "
                "and people do not have odometers."
            )
        existing = (
            await self.db.execute(
                select(TripLog).where(TripLog.assignment_id == assignment_id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise AppError(
                f"This vehicle already has a log on booking "
                f"{await self._reference(assignment.booking_id)}. A second "
                f"would double the distance in every fleet average."
            )

        previous = await self._last_closing(assignment.vehicle_id)
        try:
            notes_out = check_reading(
                Odometer(out_km=odometer_out_km), previous_in=previous
            )
        except LogRefused as exc:
            raise AppError(str(exc)) from exc

        row = TripLog(
            assignment_id=assignment.id,
            vehicle_id=assignment.vehicle_id,
            booking_id=assignment.booking_id,
            odometer_out_km=odometer_out_km,
            started_on=started_on or assignment.starts_on,
            driver_id=driver_id,
            notes=notes,
            recorded_by=actor_id,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row, notes_out

    async def close(
        self,
        log_id: uuid.UUID,
        *,
        odometer_in_km: Decimal,
        ended_on: date | None = None,
    ) -> TripLog:
        row = await self.get(log_id)
        try:
            check_reading(
                Odometer(out_km=row.odometer_out_km, in_km=odometer_in_km)
            )
        except LogRefused as exc:
            raise AppError(str(exc)) from exc
        row.odometer_in_km = odometer_in_km
        row.ended_on = ended_on or date.today()
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def fill(
        self,
        log_id: uuid.UUID,
        *,
        litres: Decimal,
        amount: Decimal,
        currency: str,
        bought_on: date | None = None,
        station: str | None = None,
        receipt_ref: str | None = None,
        notes: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> FuelFill:
        row = await self.get(log_id)
        when = bought_on or date.today()
        try:
            check_fill(
                Fill(
                    litres=litres,
                    amount=amount,
                    currency=currency,
                    bought_on=when,
                )
            )
        except LogRefused as exc:
            raise AppError(str(exc)) from exc
        fill = FuelFill(
            trip_log_id=row.id,
            litres=litres,
            amount=amount,
            currency=currency.upper(),
            bought_on=when,
            station=station,
            receipt_ref=receipt_ref,
            notes=notes,
            recorded_by=actor_id,
        )
        self.db.add(fill)
        await self.db.commit()
        await self.db.refresh(fill)
        return fill

    async def get(self, log_id: uuid.UUID) -> TripLog:
        row = await self.db.get(TripLog, log_id)
        if row is None:
            raise NotFoundError("Trip log not found.")
        return row

    async def for_booking(self, booking_id: uuid.UUID) -> list[TripLog]:
        return list(
            (
                await self.db.execute(
                    select(TripLog)
                    .where(TripLog.booking_id == booking_id)
                    .order_by(TripLog.started_on)
                )
            )
            .scalars()
            .all()
        )

    async def measured(self, log: TripLog) -> Actual:
        vehicle = await self.db.get(Vehicle, log.vehicle_id)
        try:
            return measure(
                odometer=Odometer(
                    out_km=log.odometer_out_km, in_km=log.odometer_in_km
                ),
                fills=[_fill(one) for one in log.fills],
                model_kmpl=vehicle.fuel_consumption_kmpl if vehicle else None,
            )
        except LogRefused as exc:
            raise AppError(str(exc)) from exc

    async def audit_vehicle(
        self,
        vehicle_id: uuid.UUID,
        *,
        since: date | None = None,
        tolerance_pct: Decimal | None = None,
    ) -> FleetTruth:
        vehicle = await self.db.get(Vehicle, vehicle_id)
        if vehicle is None:
            raise NotFoundError("Vehicle not found.")
        stmt = select(TripLog).where(
            TripLog.vehicle_id == vehicle_id, TripLog.odometer_in_km.is_not(None)
        )
        if since is not None:
            stmt = stmt.where(TripLog.started_on >= since)
        logs = list((await self.db.execute(stmt)).scalars().all())
        actuals = []
        for log in logs:
            try:
                actuals.append(
                    measure(
                        odometer=Odometer(
                            out_km=log.odometer_out_km, in_km=log.odometer_in_km
                        ),
                        fills=[_fill(one) for one in log.fills],
                        model_kmpl=vehicle.fuel_consumption_kmpl,
                    )
                )
            except LogRefused:
                continue
        return audit(
            vehicle.name,
            actuals,
            model_kmpl=vehicle.fuel_consumption_kmpl,
            tolerance_pct=(
                tolerance_pct if tolerance_pct is not None else DEFAULT_TOLERANCE_PCT
            ),
        )

    async def audit_fleet(
        self, *, since: date | None = None
    ) -> list[FleetTruth]:
        vehicles = list(
            (
                await self.db.execute(
                    select(Vehicle).where(Vehicle.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )
        out = [
            await self.audit_vehicle(vehicle.id, since=since)
            for vehicle in vehicles
        ]
        return sorted(out, key=_worst_first)

    async def _last_closing(self, vehicle_id: uuid.UUID) -> Decimal | None:
        return (
            await self.db.execute(
                select(TripLog.odometer_in_km)
                .where(
                    TripLog.vehicle_id == vehicle_id,
                    TripLog.odometer_in_km.is_not(None),
                )
                .order_by(TripLog.odometer_in_km.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _reference(self, booking_id: uuid.UUID) -> str:
        booking = await self.db.get(Booking, booking_id)
        return booking.reference if booking else ""


def _fill(row: FuelFill) -> Fill:
    return Fill(
        litres=row.litres,
        amount=row.amount,
        currency=row.currency,
        bought_on=row.bought_on,
    )


def _worst_first(truth: FleetTruth) -> tuple:
    variances = [
        one.variance_pct for one in truth.findings if one.variance_pct is not None
    ]
    return (min(variances) if variances else Decimal(0), truth.vehicle)


class SupplyService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(
        self,
        booking_id: uuid.UUID,
        *,
        supplier_id: uuid.UUID,
        service: str,
        expected_amount: Decimal,
        currency: str,
        check_in: date | None = None,
        check_out: date | None = None,
        confirm_by: date | None = None,
        notes: str | None = None,
        actor_id: uuid.UUID | None = None,
    ) -> SupplierBooking:
        booking = await self.db.get(Booking, booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.")
        if booking.status not in ACTIVE_STATUSES:
            raise AppError(
                f"Booking {booking.reference} is {booking.status}, so there is "
                f"nothing to buy for it."
            )
        supplier = await self.db.get(Supplier, supplier_id)
        if supplier is None:
            raise NotFoundError("Supplier not found.")
        if not (service or "").strip():
            raise AppError(
                "Say what is being bought. 'Hotel' is not something anybody can "
                "confirm — '3 x garden twin, half board' is."
            )
        if len((currency or "").strip()) != 3:
            raise AppError(
                "A supplier commitment needs a currency. Money is an amount and "
                "a currency here as everywhere else."
            )
        row = SupplierBooking(
            booking_id=booking.id,
            supplier_id=supplier.id,
            service=service.strip(),
            status=TO_REQUEST,
            expected_amount=expected_amount,
            currency=currency.upper(),
            check_in=check_in or booking.arrival_date,
            check_out=check_out or booking.departure_date,
            confirm_by=confirm_by,
            notes=notes,
            created_by=actor_id,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def get(self, supply_id: uuid.UUID) -> SupplierBooking:
        row = await self.db.get(SupplierBooking, supply_id)
        if row is None:
            raise NotFoundError("Supplier booking not found.")
        return row

    async def move(
        self,
        supply_id: uuid.UUID,
        *,
        status: str,
        their_reference: str | None = None,
        reason: str | None = None,
        on: date | None = None,
    ) -> SupplierBooking:
        row = await self.get(supply_id)
        try:
            target = normalise_status(status)
            check_transition(
                row.status,
                target,
                their_reference=their_reference or row.their_reference,
                reason=reason,
            )
        except SupplyRefused as exc:
            raise AppError(str(exc)) from exc

        when = on or date.today()
        if target == REQUESTED:
            row.requested_on = when
        elif target == CONFIRMED:
            row.confirmed_on = when
            if their_reference:
                row.their_reference = their_reference.strip()
        elif target == CANCELLED:
            row.cancel_reason = (reason or "").strip()
        row.status = target
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def invoice(
        self,
        supply_id: uuid.UUID,
        *,
        amount: Decimal,
        currency: str | None = None,
    ) -> SupplierBooking:
        row = await self.get(supply_id)
        if currency and currency.upper() != row.currency:
            raise AppError(
                f"This was committed in {row.currency} and the invoice is in "
                f"{currency.upper()}. Recording it would mean choosing an "
                f"exchange rate, which is a decision and not arithmetic."
            )
        if amount < 0:
            raise AppError("An invoice cannot be for a negative amount.")
        row.invoiced_amount = amount
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def settle(
        self,
        supply_id: uuid.UUID,
        *,
        amount: Decimal,
        on: date | None = None,
        currency: str | None = None,
    ) -> SupplierBooking:
        row = await self.get(supply_id)
        if currency and currency.upper() != row.currency:
            raise AppError(
                f"This was committed in {row.currency} and the payment is in "
                f"{currency.upper()}."
            )
        if amount < 0:
            raise AppError("A payment cannot be for a negative amount.")
        row.settled_amount = amount
        row.settled_on = on or date.today()
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def for_booking(self, booking_id: uuid.UUID) -> list[SupplierBooking]:
        return list(
            (
                await self.db.execute(
                    select(SupplierBooking)
                    .where(SupplierBooking.booking_id == booking_id)
                    .order_by(SupplierBooking.check_in, SupplierBooking.service)
                )
            )
            .scalars()
            .all()
        )

    async def position(
        self,
        booking_id: uuid.UUID,
        *,
        today: date | None = None,
        confirm_by_days: int = DEFAULT_CONFIRM_BY_DAYS,
    ) -> tuple[Exposure, list[Concern]]:
        booking = await self.db.get(Booking, booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.")
        when = today or date.today()
        rows = await self.for_booking(booking_id)
        committed = [await self._committed(row) for row in rows]
        concerns = [
            *check_supply(
                committed,
                departs_on=booking.arrival_date,
                today=when,
                confirm_by_days=confirm_by_days,
            ),
            *check_invoices(committed),
            *unsettled(
                committed, departed_on=booking.departure_date, today=when
            ),
        ]
        return exposure(committed), concerns

    async def payables(
        self, *, supplier_id: uuid.UUID | None = None
    ) -> list[SupplierBooking]:
        stmt = (
            select(SupplierBooking)
            .join(Booking, Booking.id == SupplierBooking.booking_id)
            .where(
                SupplierBooking.status != CANCELLED,
                Booking.status.in_(ACTIVE_STATUSES),
            )
            .order_by(SupplierBooking.check_in)
        )
        if supplier_id is not None:
            stmt = stmt.where(SupplierBooking.supplier_id == supplier_id)
        rows = list((await self.db.execute(stmt)).scalars().all())
        out = []
        for row in rows:
            if (await self._committed(row)).owed > 0:
                out.append(row)
        return out

    async def concerns_for(
        self,
        bookings: Sequence[Booking],
        *,
        today: date,
        confirm_by_days: int = DEFAULT_CONFIRM_BY_DAYS,
    ) -> dict[uuid.UUID, list[Concern]]:
        ids = [booking.id for booking in bookings]
        out: dict[uuid.UUID, list[Concern]] = {one: [] for one in ids}
        if not ids:
            return out
        rows = list(
            (
                await self.db.execute(
                    select(SupplierBooking).where(
                        SupplierBooking.booking_id.in_(ids)
                    )
                )
            )
            .scalars()
            .all()
        )
        names = await self._supplier_names(rows)
        by_booking: dict[uuid.UUID, list[Committed]] = {one: [] for one in ids}
        for row in rows:
            by_booking[row.booking_id].append(_committed(row, names))
        for booking in bookings:
            out[booking.id] = check_supply(
                by_booking[booking.id],
                departs_on=booking.arrival_date,
                today=today,
                confirm_by_days=confirm_by_days,
            )
        return out

    async def _committed(self, row: SupplierBooking) -> Committed:
        names = await self._supplier_names([row])
        return _committed(row, names)

    async def _supplier_names(
        self, rows: Sequence[SupplierBooking]
    ) -> dict[uuid.UUID, str]:
        ids = {row.supplier_id for row in rows}
        if not ids:
            return {}
        return {
            one.id: one.name
            for one in (
                await self.db.execute(select(Supplier).where(Supplier.id.in_(ids)))
            )
            .scalars()
            .all()
        }


def _committed(row: SupplierBooking, names: dict[uuid.UUID, str]) -> Committed:
    return Committed(
        supplier=names.get(row.supplier_id, "This supplier"),
        status=row.status,
        expected=row.expected_amount,
        invoiced=row.invoiced_amount,
        settled=row.settled_amount,
        currency=row.currency,
        check_in=row.check_in,
        confirm_by=row.confirm_by,
        their_reference=row.their_reference or "",
    )


def _crew(member: CrewMember) -> Crew:
    return Crew(
        name=member.name,
        roles=tuple(member.roles or ()),
        is_active=member.is_active,
        licence_expires_on=member.licence_expires_on,
    )


def _default_role(member: CrewMember) -> str:
    roles = list(member.roles or ())
    if len(roles) == 1:
        return roles[0]
    raise AssignmentRefused(
        f"{member.name} is down as {', '.join(roles)}. Say which of those they "
        f"are doing on this trip — a trip sheet has to name one."
    )


__all__ = [
    "AssignmentService",
    "CrewService",
    "SupplyService",
    "TripLogService",
    "normalise_roles",
]
