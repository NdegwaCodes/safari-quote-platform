from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.modules.operations.schemas import (
    ActualRead,
    AssignmentCreate,
    AssignmentMade,
    AssignmentRead,
    ClashRead,
    ConcernRead,
    CrewCreate,
    CrewRead,
    CrewUpdate,
    DepartureRead,
    ExposureRead,
    FindingRead,
    FleetTruthRead,
    FuelFillCreate,
    FuelFillRead,
    GapRead,
    RosterRead,
    SupplierAmount,
    SupplierBookingCreate,
    SupplierBookingMove,
    SupplierBookingRead,
    SupplyPositionRead,
    TripLogClose,
    TripLogOpen,
    TripLogOpened,
    TripLogRead,
)
from app.modules.operations.service import (
    AssignmentService,
    CrewService,
    SupplyService,
    TripLogService,
)
from app.modules.users.models import User

router = APIRouter(tags=["operations"])

CREW_READ = "crew:read"
CREW_MANAGE = "crew:manage"
ASSIGN_READ = "assignment:read"
ASSIGN_MANAGE = "assignment:manage"
LOG_READ = "fleet_log:read"
LOG_MANAGE = "fleet_log:manage"
SUPPLY_READ = "supply:read"
SUPPLY_MANAGE = "supply:manage"


@router.post("/crew", response_model=CrewRead, status_code=201)
async def create_crew(
    body: CrewCreate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(CREW_MANAGE)),
):
    return await CrewService(db).create(body.model_dump(exclude_unset=True))


@router.get("/crew", response_model=list[CrewRead])
async def list_crew(
    role: str | None = Query(
        default=None, description="driver | guide | driver_guide"
    ),
    active_only: bool = Query(default=True),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(CREW_READ)),
):
    return await CrewService(db).list(role=role, active_only=active_only)


@router.get("/crew/{crew_id}", response_model=CrewRead)
async def get_crew(
    crew_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(CREW_READ)),
):
    return await CrewService(db).get(crew_id)


@router.patch("/crew/{crew_id}", response_model=CrewRead)
async def update_crew(
    crew_id: uuid.UUID,
    body: CrewUpdate,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(CREW_MANAGE)),
):
    return await CrewService(db).update(
        crew_id, body.model_dump(exclude_unset=True)
    )


@router.post(
    "/bookings/{booking_id}/assignments",
    response_model=AssignmentMade,
    status_code=201,
)
async def assign(
    booking_id: uuid.UUID,
    body: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(ASSIGN_MANAGE)),
):
    assignment, advisories = await AssignmentService(db).assign(
        booking_id, actor_id=actor.id, **body.model_dump(exclude_unset=True)
    )
    return AssignmentMade(
        assignment=AssignmentRead.model_validate(assignment),
        advisories=[ClashRead(**vars(one)) for one in advisories],
    )


@router.get(
    "/bookings/{booking_id}/assignments", response_model=list[AssignmentRead]
)
async def booking_assignments(
    booking_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(ASSIGN_READ)),
):
    return await AssignmentService(db).for_booking(booking_id)


@router.get("/bookings/{booking_id}/readiness", response_model=list[GapRead])
async def readiness(
    booking_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(ASSIGN_READ)),
):
    return await AssignmentService(db).readiness(booking_id)


@router.delete("/assignments/{assignment_id}", status_code=204)
async def release(
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(ASSIGN_MANAGE)),
):
    await AssignmentService(db).release(assignment_id)


@router.get("/operations/departures", response_model=list[DepartureRead])
async def departures(
    days: int = Query(default=14, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(ASSIGN_READ)),
):
    found = await AssignmentService(db).departures(days=days)
    supply = await SupplyService(db).concerns_for(
        [booking for booking, _roster, _gaps in found], today=date.today()
    )
    return [
        DepartureRead(
            booking_id=booking.id,
            reference=booking.reference,
            arrival_date=booking.arrival_date,
            departure_date=booking.departure_date,
            pax_count=booking.pax_count,
            status=booking.status,
            roster=RosterRead(
                vehicles=[one.name for one in roster.vehicles],
                drivers=[one.name for one in roster.drivers],
                guides=[one.name for one in roster.guides],
                seats=roster.seats,
            ),
            gaps=[GapRead(**vars(one)) for one in gaps],
            supply=[
                ConcernRead(**vars(one)) for one in supply.get(booking.id, [])
            ],
        )
        for booking, roster, gaps in found
    ]


@router.get("/operations/diary", response_model=list[AssignmentRead])
async def diary(
    starts_on: date = Query(description="First day of the span."),
    ends_on: date = Query(description="Last day of the span, inclusive."),
    vehicle_id: uuid.UUID | None = Query(default=None),
    crew_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(ASSIGN_READ)),
):
    return await AssignmentService(db).diary(
        starts_on=starts_on,
        ends_on=ends_on,
        vehicle_id=vehicle_id,
        crew_id=crew_id,
    )


@router.post(
    "/assignments/{assignment_id}/log",
    response_model=TripLogOpened,
    status_code=201,
)
async def open_log(
    assignment_id: uuid.UUID,
    body: TripLogOpen,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(LOG_MANAGE)),
):
    log, observations = await TripLogService(db).open(
        assignment_id, actor_id=actor.id, **body.model_dump(exclude_unset=True)
    )
    return TripLogOpened(
        log=_log(log), observations=observations
    )


@router.post("/trip-logs/{log_id}/close", response_model=TripLogRead)
async def close_log(
    log_id: uuid.UUID,
    body: TripLogClose,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(LOG_MANAGE)),
):
    return _log(
        await TripLogService(db).close(
            log_id,
            odometer_in_km=body.odometer_in_km,
            ended_on=body.ended_on,
        )
    )


@router.post(
    "/trip-logs/{log_id}/fuel", response_model=FuelFillRead, status_code=201
)
async def add_fuel(
    log_id: uuid.UUID,
    body: FuelFillCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(LOG_MANAGE)),
):
    return await TripLogService(db).fill(
        log_id, actor_id=actor.id, **body.model_dump(exclude_unset=True)
    )


@router.get("/trip-logs/{log_id}/actual", response_model=ActualRead)
async def trip_actual(
    log_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(LOG_READ)),
):
    service = TripLogService(db)
    actual = await service.measured(await service.get(log_id))
    return ActualRead(
        distance_km=actual.distance_km,
        litres=actual.litres,
        fuel_cost=actual.fuel_cost,
        currency=actual.currency,
        model_kmpl=actual.model_kmpl,
        actual_kmpl=actual.actual_kmpl,
        model_litres=actual.model_litres,
        variance_pct=actual.variance_pct,
    )


@router.get("/bookings/{booking_id}/trip-logs", response_model=list[TripLogRead])
async def booking_logs(
    booking_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(LOG_READ)),
):
    return [_log(one) for one in await TripLogService(db).for_booking(booking_id)]


@router.get("/operations/fuel-audit", response_model=list[FleetTruthRead])
async def fuel_audit(
    since: date | None = Query(
        default=None, description="Only trips starting on or after this day."
    ),
    vehicle_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(LOG_READ)),
):
    service = TripLogService(db)
    found = (
        [await service.audit_vehicle(vehicle_id, since=since)]
        if vehicle_id
        else await service.audit_fleet(since=since)
    )
    return [
        FleetTruthRead(
            vehicle=one.vehicle,
            trips=one.trips,
            distance_km=one.distance_km,
            litres=one.litres,
            fuel_cost=one.fuel_cost,
            currency=one.currency,
            model_kmpl=one.model_kmpl,
            actual_kmpl=one.actual_kmpl,
            findings=[FindingRead(**vars(f)) for f in one.findings],
        )
        for one in found
    ]


def _log(row) -> TripLogRead:
    return TripLogRead(
        **{
            key: getattr(row, key)
            for key in (
                "id",
                "assignment_id",
                "vehicle_id",
                "booking_id",
                "odometer_out_km",
                "odometer_in_km",
                "started_on",
                "ended_on",
                "driver_id",
                "notes",
            )
        },
        distance_km=row.distance_km,
        is_open=row.is_open,
        fills=[FuelFillRead.model_validate(one) for one in row.fills],
    )


@router.post(
    "/bookings/{booking_id}/suppliers",
    response_model=SupplierBookingRead,
    status_code=201,
)
async def add_supplier(
    booking_id: uuid.UUID,
    body: SupplierBookingCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(SUPPLY_MANAGE)),
):
    return await SupplyService(db).add(
        booking_id, actor_id=actor.id, **body.model_dump(exclude_unset=True)
    )


@router.get(
    "/bookings/{booking_id}/suppliers", response_model=list[SupplierBookingRead]
)
async def booking_suppliers(
    booking_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(SUPPLY_READ)),
):
    return await SupplyService(db).for_booking(booking_id)


@router.post(
    "/supplier-bookings/{supply_id}/status", response_model=SupplierBookingRead
)
async def move_supplier(
    supply_id: uuid.UUID,
    body: SupplierBookingMove,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(SUPPLY_MANAGE)),
):
    return await SupplyService(db).move(
        supply_id,
        status=body.status,
        their_reference=body.their_reference,
        reason=body.reason,
        on=body.on,
    )


@router.post(
    "/supplier-bookings/{supply_id}/invoice", response_model=SupplierBookingRead
)
async def record_invoice(
    supply_id: uuid.UUID,
    body: SupplierAmount,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(SUPPLY_MANAGE)),
):
    return await SupplyService(db).invoice(
        supply_id, amount=body.amount, currency=body.currency
    )


@router.post(
    "/supplier-bookings/{supply_id}/settle", response_model=SupplierBookingRead
)
async def record_settlement(
    supply_id: uuid.UUID,
    body: SupplierAmount,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(SUPPLY_MANAGE)),
):
    return await SupplyService(db).settle(
        supply_id, amount=body.amount, currency=body.currency, on=body.on
    )


@router.get(
    "/bookings/{booking_id}/supply-position", response_model=SupplyPositionRead
)
async def supply_position(
    booking_id: uuid.UUID,
    confirm_by_days: int = Query(
        default=14,
        ge=1,
        le=365,
        description="Days before departure an unconfirmed supplier is a problem.",
    ),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(SUPPLY_READ)),
):
    found, concerns = await SupplyService(db).position(
        booking_id, confirm_by_days=confirm_by_days
    )
    return SupplyPositionRead(
        exposure=ExposureRead(
            expected=found.expected,
            invoiced=found.invoiced,
            settled=found.settled,
            owed=found.owed,
            suppliers=found.suppliers,
            unconfirmed=found.unconfirmed,
            all_confirmed=found.all_confirmed,
        ),
        concerns=[ConcernRead(**vars(one)) for one in concerns],
    )


@router.get("/operations/payables", response_model=list[SupplierBookingRead])
async def payables(
    supplier_id: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(SUPPLY_READ)),
):
    return await SupplyService(db).payables(supplier_id=supplier_id)
