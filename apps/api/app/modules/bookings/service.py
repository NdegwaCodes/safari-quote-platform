from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.modules.bookings.cancellation import (
    Cancellation,
    PeakPeriod,
    Settlement,
    check_cancellation,
    settle_cancellation,
)
from app.modules.bookings.models import (
    ACTIVE_STATUSES,
    CANCELLED,
    COMPLETED,
    CONFIRMED,
    PAYMENT_METHODS,
    PROVISIONAL,
    Booking,
    BookingCounter,
    BookingInstalment,
    Payment,
)
from app.modules.bookings.schedule import (
    Instalment,
    Owed,
    ScheduleRefused,
    build,
    is_confirmable,
    owed,
)
from app.modules.pricing.service import PricingConfigService
from app.modules.quotes.models import Quote, QuoteVersion
from app.modules.quotes.outcomes import ACCEPTED


def normalise_method(value: str | None) -> str:
    cleaned = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return cleaned or "other"


class BookingNumberService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def next_reference(self, year: int) -> str:
        counter = await self.db.get(BookingCounter, year, with_for_update=True)
        if counter is None:
            self.db.add(BookingCounter(year=year, last_value=0))
            await self.db.flush()
            counter = await self.db.get(BookingCounter, year, with_for_update=True)
        assert counter is not None
        counter.last_value += 1
        await self.db.flush()
        return f"HTB-{year}-{counter.last_value:04d}"


class BookingService:
    def __init__(self, db: AsyncSession):
        self.db = db


    async def create_from_quote(
        self,
        quote_id: uuid.UUID,
        *,
        actor_id: uuid.UUID | None,
        notes: str | None = None,
        is_exclusive_use: bool = False,
        today: date | None = None,
    ) -> Booking:
        when = today or date.today()
        quote = (
            await self.db.execute(select(Quote).where(Quote.id == quote_id))
        ).scalar_one_or_none()
        if quote is None:
            raise NotFoundError("Quote not found.")
        if quote.status != ACCEPTED:
            raise AppError(
                f"This quote is {quote.status}, not accepted. Record the "
                f"client's acceptance first — a booking is the operational "
                f"record of a sale, and there is no sale yet."
            )
        if quote.current_version_id is None:
            raise AppError(
                "This quote has no issued version, so there is no figure to "
                "invoice. Issue it, then accept it, then book it."
            )
        existing = (
            (
                await self.db.execute(
                    select(Booking).where(
                        Booking.quote_id == quote_id,
                        Booking.status.in_(ACTIVE_STATUSES),
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            raise AppError(
                f"This quote is already booked as {existing.reference}. One "
                f"trip cannot be held twice — cancel that booking first if it "
                f"is being replaced."
            )

        version = await self.db.get(QuoteVersion, quote.current_version_id)
        if version is None:
            raise NotFoundError("The quote's issued version is missing.")

        cfg = await PricingConfigService(self.db).get()
        try:
            instalments = build(
                Decimal(version.selling_price),
                version.currency,
                deposit_pct=cfg.deposit_pct,
                travel_from=quote.arrival_date,
                balance_due_days_before=cfg.balance_due_days_before_travel,
                today=when,
            )
        except ScheduleRefused as exc:
            raise AppError(str(exc)) from exc

        booking = Booking(
            reference=await BookingNumberService(self.db).next_reference(when.year),
            quote_id=quote.id,
            quote_version_id=version.id,
            option_id=quote.selected_option_id,
            client_id=quote.client_id,
            status=PROVISIONAL,
            arrival_date=quote.arrival_date,
            departure_date=quote.departure_date,
            pax_count=int((version.snapshot or {}).get("pax_count") or quote.pax_count or 0),
            total_amount=Decimal(version.selling_price),
            currency=version.currency.upper(),
            notes=notes,
            is_exclusive_use=is_exclusive_use,
            created_by=actor_id,
        )
        for instalment in instalments:
            booking.instalments.append(
                BookingInstalment(
                    label=instalment.label,
                    due_on=instalment.due_on,
                    amount=instalment.amount,
                    currency=instalment.currency,
                    sort_order=instalment.sort_order,
                )
            )
        self.db.add(booking)
        await self.db.commit()
        return await self.get(booking.id)

    async def get(self, booking_id: uuid.UUID) -> Booking:
        booking = (
            await self.db.execute(select(Booking).where(Booking.id == booking_id))
        ).scalar_one_or_none()
        if booking is None:
            raise NotFoundError("Booking not found.")
        return booking


    async def record_payment(
        self,
        booking_id: uuid.UUID,
        *,
        amount: Decimal,
        paid_on: date,
        method: str | None,
        currency: str | None = None,
        reference: str | None = None,
        instalment_id: uuid.UUID | None = None,
        notes: str | None = None,
        actor_id: uuid.UUID | None = None,
        today: date | None = None,
    ) -> Booking:
        booking = await self.get(booking_id)
        if booking.status == CANCELLED:
            raise AppError(
                f"{booking.reference} is cancelled. Record a refund against it "
                f"rather than a payment, or reinstate it first."
            )
        code = (currency or booking.currency).upper()
        if code != booking.currency.upper():
            raise AppError(
                f"{booking.reference} is invoiced in {booking.currency} and "
                f"this payment is in {code}. What cleared is a fact and the "
                f"exchange rate is a decision — record the amount in "
                f"{booking.currency} that reached the account, and keep the "
                f"rate you used in the notes."
            )
        if instalment_id is not None:
            target = await self.db.get(BookingInstalment, instalment_id)
            if target is None or target.booking_id != booking.id:
                raise NotFoundError(
                    "That instalment does not belong to this booking."
                )

        self.db.add(
            Payment(
                booking_id=booking.id,
                amount=amount,
                currency=code,
                paid_on=paid_on,
                method=normalise_method(method),
                reference=reference,
                instalment_id=instalment_id,
                notes=notes,
                recorded_by=actor_id,
            )
        )
        await self.db.flush()
        await self.db.refresh(booking)

        if booking.status == PROVISIONAL and is_confirmable(
            [_instalment(row) for row in booking.instalments],
            [row.amount for row in booking.payments],
        ):
            booking.status = CONFIRMED
            booking.confirmed_at = datetime.now(UTC)
        await self.db.commit()
        return await self.get(booking_id)

    async def position(
        self, booking_id: uuid.UUID, *, today: date | None = None
    ) -> Owed:
        booking = await self.get(booking_id)
        return owed(
            [_instalment(row) for row in booking.instalments],
            [row.amount for row in booking.payments],
            total=booking.total_amount,
            currency=booking.currency,
            today=today or date.today(),
        )

    async def settlement(self, booking_id: uuid.UUID) -> Settlement:
        booking = await self.get(booking_id)
        if booking.status != CANCELLED:
            raise AppError(
                f"{booking.reference} is not cancelled, so there is no "
                f"cancellation settlement to report — see /owed for what a "
                f"live booking stands at."
            )
        assert booking.retained_amount is not None
        paid = sum((row.amount for row in booking.payments), Decimal(0))
        return settle_cancellation(
            retained_amount=booking.retained_amount, paid_amount=paid
        )


    async def preview_cancellation(
        self, booking_id: uuid.UUID, *, today: date | None = None
    ) -> Cancellation:
        booking = await self.get(booking_id)
        return await self._cancellation_for(booking, on=today or date.today())

    async def cancel(
        self,
        booking_id: uuid.UUID,
        *,
        reason: str,
        actor_id: uuid.UUID | None = None,
        today: date | None = None,
    ) -> Booking:
        booking = await self.get(booking_id)
        if booking.status == CANCELLED:
            return booking
        if booking.status == COMPLETED:
            raise AppError(
                f"{booking.reference} is completed — they have travelled. A "
                f"trip that happened cannot be cancelled; record what needs "
                f"recording against it instead."
            )
        if not (reason or "").strip():
            raise AppError("Say why the booking was cancelled.")

        found = await self._cancellation_for(booking, on=today or date.today())
        booking.status = CANCELLED
        booking.cancelled_at = datetime.now(UTC)
        booking.cancellation_reason = reason
        booking.retained_amount = found.retained_amount
        booking.cancellation_band = found.band
        booking.cancellation_notice_days = found.notice_days
        await self.db.commit()
        return await self.get(booking_id)

    async def _cancellation_for(self, booking: Booking, *, on: date) -> Cancellation:
        cfg = await PricingConfigService(self.db).get()
        peaks = [
            PeakPeriod(start=row.start, end=row.end, label=row.label)
            for row in cfg.cancellation_peak_periods
        ]
        return check_cancellation(
            total_amount=booking.total_amount,
            departure_date=booking.departure_date,
            notice_on=on,
            pax_count=booking.pax_count,
            is_exclusive_use=booking.is_exclusive_use,
            deposit_pct=cfg.deposit_pct,
            tier1_days=cfg.cancellation_tier1_days,
            tier2_days=cfg.cancellation_tier2_days,
            tier2_pct=cfg.cancellation_tier2_pct,
            tier3_days=cfg.cancellation_tier3_days,
            tier3_pct=cfg.cancellation_tier3_pct,
            forfeit_pct=cfg.cancellation_forfeit_pct,
            group_pax_threshold=cfg.cancellation_group_pax_threshold,
            group_notice_extension_days=cfg.cancellation_group_notice_extension_days,
            peak_periods=peaks,
        )

    async def complete(
        self, booking_id: uuid.UUID, *, today: date | None = None
    ) -> Booking:
        booking = await self.get(booking_id)
        when = today or date.today()
        if booking.status == CANCELLED:
            raise AppError(
                f"{booking.reference} was cancelled, so it did not happen."
            )
        if when < booking.departure_date:
            raise AppError(
                f"{booking.reference} departs on {booking.departure_date}. A "
                f"trip cannot be completed before it has finished."
            )
        booking.status = COMPLETED
        booking.completed_at = datetime.now(UTC)
        await self.db.commit()
        return await self.get(booking_id)

    async def due(
        self, *, today: date | None = None, within_days: int = 7
    ) -> list[tuple[Booking, Owed]]:
        when = today or date.today()
        rows = list(
            (
                await self.db.execute(
                    select(Booking).where(Booking.status.in_(ACTIVE_STATUSES))
                )
            )
            .scalars()
            .all()
        )
        out: list[tuple[Booking, Owed]] = []
        for booking in rows:
            position = owed(
                [_instalment(one) for one in booking.instalments],
                [one.amount for one in booking.payments],
                total=booking.total_amount,
                currency=booking.currency,
                today=when,
            )
            if position.is_settled:
                continue
            soon = position.next_due is not None and (
                position.next_due.due_on - when
            ).days <= within_days
            if position.overdue or soon:
                out.append((booking, position))
        out.sort(
            key=lambda pair: (
                pair[1].next_due.due_on if pair[1].next_due else pair[0].arrival_date
            )
        )
        return out


def _instalment(row: BookingInstalment) -> Instalment:
    return Instalment(
        label=row.label,
        due_on=row.due_on,
        amount=Decimal(row.amount),
        currency=row.currency,
        sort_order=row.sort_order,
    )


__all__ = [
    "PAYMENT_METHODS",
    "BookingNumberService",
    "BookingService",
    "normalise_method",
]
