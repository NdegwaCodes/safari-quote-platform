from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError, NotFoundError
from app.core.security import hash_refresh_token
from app.modules.bookings.models import CANCELLED as BOOKING_CANCELLED
from app.modules.bookings.models import Booking
from app.modules.bookings.schedule import Owed
from app.modules.bookings.service import BookingService
from app.modules.portal.models import BookingAccessGrant
from app.modules.portal.view import (
    AccessRefused,
    Grant,
    Trip,
    check_access,
    default_expiry,
    trip_of,
)
from app.modules.quotes.models import QuoteVersion


def new_token() -> str:
    return secrets.token_urlsafe(32)


class PortalService:
    def __init__(self, db: AsyncSession):
        self.db = db


    async def issue(
        self,
        booking_id: uuid.UUID,
        *,
        label: str | None = None,
        expires_on: date | None = None,
        actor_id: uuid.UUID | None = None,
        today: date | None = None,
    ) -> tuple[BookingAccessGrant, str, str]:
        booking = await self.db.get(Booking, booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.")
        if booking.status == BOOKING_CANCELLED:
            raise AppError(
                f"Booking {booking.reference} has been cancelled, so there is "
                f"no trip for a link to open. That conversation is a phone "
                f"call, not a link."
            )
        when = today or date.today()
        last_day = expires_on or default_expiry(
            booking.departure_date,
            after_days=settings.PORTAL_ACCESS_DAYS_AFTER_TRAVEL,
            today=when,
        )
        if last_day < when:
            raise AppError(
                "A link cannot expire in the past — it would never work once."
            )

        token = new_token()
        grant = BookingAccessGrant(
            booking_id=booking.id,
            token_hash=hash_refresh_token(token),
            label=(label or "").strip() or None,
            expires_on=last_day,
            created_by=actor_id,
        )
        self.db.add(grant)
        await self.db.commit()
        await self.db.refresh(grant)
        return grant, token, link_for(token)

    async def grants(self, booking_id: uuid.UUID) -> list[BookingAccessGrant]:
        return list(
            (
                await self.db.execute(
                    select(BookingAccessGrant)
                    .where(BookingAccessGrant.booking_id == booking_id)
                    .order_by(BookingAccessGrant.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    async def revoke(
        self,
        grant_id: uuid.UUID,
        *,
        reason: str,
        actor_id: uuid.UUID | None = None,
    ) -> BookingAccessGrant:
        grant = await self.db.get(BookingAccessGrant, grant_id)
        if grant is None:
            raise NotFoundError("Access link not found.")
        if not reason.strip():
            raise AppError(
                "Say why this link is being withdrawn. Without a reason the "
                "next person cannot tell a leak from a mistake."
            )
        if grant.is_revoked:
            raise AppError("This link has already been withdrawn.")
        grant.revoked_at = datetime.now(UTC)
        grant.revoked_by = actor_id
        grant.revoke_reason = reason.strip()
        await self.db.commit()
        await self.db.refresh(grant)
        return grant


    async def resolve(
        self, token: str, *, today: date | None = None, record_visit: bool = True
    ) -> tuple[BookingAccessGrant, Booking]:
        when = today or date.today()
        grant = (
            await self.db.execute(
                select(BookingAccessGrant).where(
                    BookingAccessGrant.token_hash == hash_refresh_token(token or "")
                )
            )
        ).scalar_one_or_none()
        if grant is None:
            raise AccessRefused(
                "portal_link_unknown",
                "This link does not work. Ask your consultant to send a fresh "
                "one — nothing about your booking has changed.",
            )
        booking = await self.db.get(Booking, grant.booking_id)
        if booking is None:
            raise AccessRefused(
                "portal_link_unknown",
                "This link does not work. Ask your consultant to send a fresh "
                "one.",
            )
        check_access(
            Grant(
                expires_on=grant.expires_on,
                revoked=grant.is_revoked,
                revoke_reason=grant.revoke_reason,
                booking_status=booking.status,
                booking_reference=booking.reference,
            ),
            today=when,
        )
        if record_visit:
            grant.last_seen_at = datetime.now(UTC)
            grant.view_count = (grant.view_count or 0) + 1
            await self.db.commit()
            await self.db.refresh(grant)
        return grant, booking


    async def trip(self, booking: Booking) -> Trip:
        version = await self.db.get(QuoteVersion, booking.quote_version_id)
        snapshot = version.snapshot if version is not None else {}
        return trip_of(
            snapshot if isinstance(snapshot, dict) else {},
            option_id=str(booking.option_id) if booking.option_id else None,
            reference=booking.reference,
            status=booking.status,
            arrival=booking.arrival_date,
            departure=booking.departure_date,
            pax_count=booking.pax_count,
            total=booking.total_amount,
            currency=booking.currency,
        )

    async def statement(
        self, booking: Booking, *, today: date | None = None
    ) -> Owed:
        return await BookingService(self.db).position(booking.id, today=today)


def link_for(token: str) -> str:
    return f"{settings.PORTAL_BASE_URL.rstrip('/')}/trip#{token}"


__all__ = ["PortalService", "link_for", "new_token"]
