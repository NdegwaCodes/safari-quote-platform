from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.core.errors import AppError
from app.db.session import get_db
from app.modules.bookings.models import Booking
from app.modules.documents.service import QuotationDocumentService
from app.modules.portal.schemas import (
    DayRead,
    GrantCreate,
    GrantIssued,
    GrantRead,
    GrantRevoke,
    InstalmentRead,
    MovementRead,
    PaymentRead,
    StatementRead,
    StayRead,
    TripRead,
)
from app.modules.portal.service import PortalService
from app.modules.portal.view import AccessRefused
from app.modules.users.models import User

router = APIRouter(tags=["portal"])

MANAGE = "portal:manage"


class PortalAccessDenied(AppError):

    status_code = 403

    def __init__(self, code: str, message: str):
        self.code = code.upper()
        super().__init__(message)


async def portal_access(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> tuple[uuid.UUID, Booking]:
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        raise PortalAccessDenied(
            "portal_no_link",
            "Open your trip using the link your consultant sent you.",
        )
    try:
        grant, booking = await PortalService(db).resolve(token)
    except AccessRefused as exc:
        raise PortalAccessDenied(exc.code, exc.message) from exc
    return grant.id, booking


@router.post(
    "/bookings/{booking_id}/portal-links",
    response_model=GrantIssued,
    status_code=201,
)
async def issue_link(
    booking_id: uuid.UUID,
    body: GrantCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE)),
):
    grant, token, url = await PortalService(db).issue(
        booking_id,
        label=body.label,
        expires_on=body.expires_on,
        actor_id=actor.id,
    )
    return GrantIssued(
        **GrantRead.model_validate(grant).model_dump(), token=token, url=url
    )


@router.get(
    "/bookings/{booking_id}/portal-links", response_model=list[GrantRead]
)
async def list_links(
    booking_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(MANAGE)),
):
    return await PortalService(db).grants(booking_id)


@router.post("/portal-links/{grant_id}/revoke", response_model=GrantRead)
async def revoke_link(
    grant_id: uuid.UUID,
    body: GrantRevoke,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE)),
):
    return await PortalService(db).revoke(
        grant_id, reason=body.reason, actor_id=actor.id
    )


@router.get("/portal/trip", response_model=TripRead)
async def my_trip(
    access: tuple[uuid.UUID, Booking] = Depends(portal_access),
    db: AsyncSession = Depends(get_db),
):
    _grant_id, booking = access
    return _trip(await PortalService(db).trip(booking))


@router.get("/portal/statement", response_model=StatementRead)
async def my_statement(
    access: tuple[uuid.UUID, Booking] = Depends(portal_access),
    db: AsyncSession = Depends(get_db),
):
    _grant_id, booking = access
    owed = await PortalService(db).statement(booking)
    return StatementRead(
        reference=booking.reference,
        currency=owed.currency,
        total=owed.total,
        paid=owed.paid,
        balance=owed.balance,
        overpaid=owed.overpaid,
        is_settled=owed.is_settled,
        schedule=[
            InstalmentRead(
                label=row.label,
                due_on=row.due_on,
                amount=row.amount,
                currency=owed.currency,
            )
            for row in sorted(booking.instalments, key=lambda one: one.sort_order)
        ],
        payments=[
            PaymentRead(
                amount=row.amount,
                currency=row.currency,
                paid_on=row.paid_on,
                method=row.method,
                reference=row.reference,
            )
            for row in sorted(booking.payments, key=lambda one: one.paid_on)
        ],
        overdue=[
            InstalmentRead(
                label=row.label,
                due_on=row.due_on,
                amount=row.amount,
                currency=owed.currency,
            )
            for row in owed.overdue
        ],
        next_due=(
            InstalmentRead(
                label=owed.next_due.label,
                due_on=owed.next_due.due_on,
                amount=owed.next_due.amount,
                currency=owed.currency,
            )
            if owed.next_due
            else None
        ),
    )


@router.get("/portal/document.html", response_class=HTMLResponse)
async def my_document(
    access: tuple[uuid.UUID, Booking] = Depends(portal_access),
    db: AsyncSession = Depends(get_db),
):
    _grant_id, booking = access
    version_number = await _version_number(db, booking)
    html = await QuotationDocumentService(db).render_html(
        booking.quote_id, version_number=version_number, inline_assets=True
    )
    return HTMLResponse(content=html)


async def _version_number(db: AsyncSession, booking: Booking) -> int | None:
    from app.modules.quotes.models import QuoteVersion

    version = await db.get(QuoteVersion, booking.quote_version_id)
    return version.version_number if version is not None else None


def _trip(trip) -> TripRead:
    return TripRead(
        reference=trip.reference,
        status=trip.status,
        arrival_date=trip.arrival_date,
        departure_date=trip.departure_date,
        pax_count=trip.pax_count,
        total=trip.total,
        currency=trip.currency,
        property_name=trip.property_name,
        room_type=trip.room_type,
        board=trip.board,
        nights=trip.nights,
        description=trip.description,
        stays=[StayRead(**vars(one)) for one in trip.stays],
        days=[
            DayRead(
                number=one.number,
                on=one.on,
                destination=one.destination,
                property_name=one.property_name,
                board=one.board,
                movements=[MovementRead(**vars(move)) for move in one.movements],
                excursions=one.excursions,
                is_arrival=one.is_arrival,
                is_departure=one.is_departure,
                has_night=one.has_night,
            )
            for one in trip.days
        ],
        included=trip.included,
    )
