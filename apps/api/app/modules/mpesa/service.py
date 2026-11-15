from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.integrations.mpesa import (
    MpesaClient,
    MpesaError,
    StkPushResult,
    normalise_phone,
)
from app.modules.bookings.models import CANCELLED, Booking, BookingInstalment, Payment
from app.modules.bookings.service import BookingService
from app.modules.mpesa.models import COMPLETED, FAILED, PENDING, MpesaTransaction


class MpesaService:
    def __init__(self, db: AsyncSession, *, client: MpesaClient | None = None):
        self.db = db
        self.client = client

    def _require_client(self) -> MpesaClient:
        if self.client is None:
            raise RuntimeError(
                "This operation needs an MpesaClient; construct "
                "MpesaService(db, client=...) rather than the no-argument form."
            )
        return self.client

    async def initiate(
        self,
        booking_id: uuid.UUID,
        *,
        phone_number: str,
        amount: Decimal,
        instalment_id: uuid.UUID | None = None,
        actor_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> MpesaTransaction:
        booking = await self.db.get(Booking, booking_id)
        if booking is None:
            raise NotFoundError("Booking not found.")
        if booking.status == CANCELLED:
            raise AppError(
                f"{booking.reference} is cancelled. There is nothing to "
                f"collect an M-Pesa payment against."
            )
        if booking.currency.upper() != "KES":
            raise AppError(
                f"{booking.reference} is invoiced in {booking.currency}. "
                f"M-Pesa moves Kenyan shillings only — take this payment "
                f"another way, or record it manually once it arrives."
            )
        if amount <= 0:
            raise AppError("The amount to collect must be more than zero.")
        if instalment_id is not None:
            target = await self.db.get(BookingInstalment, instalment_id)
            if target is None or target.booking_id != booking.id:
                raise NotFoundError(
                    "That instalment does not belong to this booking."
                )

        try:
            normalise_phone(phone_number)
        except ValueError as exc:
            raise AppError(str(exc)) from exc

        accepted = await self._require_client().initiate_stk_push(
            phone_number=phone_number,
            amount=amount,
            account_reference=booking.reference,
            description=f"{booking.reference} payment",
            now=now or datetime.now(UTC),
        )

        transaction = MpesaTransaction(
            booking_id=booking.id,
            instalment_id=instalment_id,
            phone_number=normalise_phone(phone_number),
            amount=amount,
            status=PENDING,
            merchant_request_id=accepted.merchant_request_id,
            checkout_request_id=accepted.checkout_request_id,
            initiated_by=actor_id,
        )
        self.db.add(transaction)
        await self.db.commit()
        await self.db.refresh(transaction)
        return transaction

    async def settle(
        self, result: StkPushResult, *, today: date | None = None
    ) -> MpesaTransaction | None:
        transaction = (
            await self.db.execute(
                select(MpesaTransaction).where(
                    MpesaTransaction.checkout_request_id == result.checkout_request_id
                )
            )
        ).scalar_one_or_none()
        if transaction is None:
            return None
        if transaction.status != PENDING:
            return transaction

        transaction.result_code = result.result_code
        transaction.result_desc = result.result_desc
        transaction.callback_received_at = datetime.now(UTC)
        transaction.mpesa_receipt_number = result.mpesa_receipt_number

        if not result.succeeded:
            transaction.status = FAILED
            await self.db.commit()
            await self.db.refresh(transaction)
            return transaction

        await BookingService(self.db).record_payment(
            transaction.booking_id,
            amount=result.amount or transaction.amount,
            paid_on=today or date.today(),
            method="mpesa",
            currency="KES",
            reference=result.mpesa_receipt_number,
            instalment_id=transaction.instalment_id,
            notes="Recorded automatically from an M-Pesa STK push callback.",
        )
        payment_id = (
            await self.db.execute(
                select(Payment.id)
                .where(
                    Payment.booking_id == transaction.booking_id,
                    Payment.reference == result.mpesa_receipt_number,
                )
                .order_by(Payment.created_at.desc())
                .limit(1)
            )
        ).scalar_one()
        transaction.status = COMPLETED
        transaction.payment_id = payment_id
        await self.db.commit()
        await self.db.refresh(transaction)
        return transaction

    async def get(self, transaction_id: uuid.UUID) -> MpesaTransaction:
        transaction = await self.db.get(MpesaTransaction, transaction_id)
        if transaction is None:
            raise NotFoundError("No such M-Pesa transaction.")
        return transaction

    async def refresh_from_daraja(
        self, transaction_id: uuid.UUID, *, now: datetime | None = None
    ) -> MpesaTransaction:
        transaction = await self.get(transaction_id)
        if transaction.status != PENDING:
            return transaction
        try:
            result = await self._require_client().query_stk_push(
                checkout_request_id=transaction.checkout_request_id,
                now=now or datetime.now(UTC),
            )
        except MpesaError:
            return transaction
        settled = await self.settle(result)
        return settled or transaction


__all__ = ["MpesaService"]
