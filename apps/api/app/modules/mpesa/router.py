from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_permission
from app.core.errors import NotFoundError
from app.core.limits import rate_limit
from app.db.session import get_db
from app.integrations.mpesa import MpesaClient, get_mpesa_client, parse_stk_callback
from app.modules.mpesa.schemas import (
    MpesaTransactionRead,
    StkPushAcceptedRead,
    StkPushCreate,
)
from app.modules.mpesa.service import MpesaService
from app.modules.users.models import User

router = APIRouter(tags=["mpesa"])


async def _owned(db, booking_id: uuid.UUID, transaction_id: uuid.UUID):
    transaction = await MpesaService(db).get(transaction_id)
    if transaction.booking_id != booking_id:
        raise NotFoundError("No such M-Pesa transaction on this booking.")
    return transaction

READ = "booking:read"
PAY = "booking:record_payment"

_callback_limit = Depends(
    rate_limit(bucket="mpesa_callback", limit=settings.PUBLIC_READ_PER_MINUTE, seconds=60)
)


@router.post(
    "/bookings/{booking_id}/payments/mpesa",
    response_model=StkPushAcceptedRead,
    status_code=202,
)
async def push_stk(
    booking_id: uuid.UUID,
    body: StkPushCreate,
    db: AsyncSession = Depends(get_db),
    client: MpesaClient = Depends(get_mpesa_client),
    actor: User = Depends(require_permission(PAY)),
):
    transaction = await MpesaService(db, client=client).initiate(
        booking_id,
        phone_number=body.phone_number,
        amount=body.amount,
        instalment_id=body.instalment_id,
        actor_id=actor.id,
    )
    return StkPushAcceptedRead(
        transaction_id=transaction.id,
        customer_message=(
            "The customer's phone has been prompted for their M-Pesa PIN."
        ),
    )


@router.get(
    "/bookings/{booking_id}/payments/mpesa/{transaction_id}",
    response_model=MpesaTransactionRead,
)
async def get_stk_push(
    booking_id: uuid.UUID,
    transaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(READ)),
):
    return await _owned(db, booking_id, transaction_id)


@router.post(
    "/bookings/{booking_id}/payments/mpesa/{transaction_id}/refresh",
    response_model=MpesaTransactionRead,
)
async def refresh_stk_push(
    booking_id: uuid.UUID,
    transaction_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    client: MpesaClient = Depends(get_mpesa_client),
    _: User = Depends(require_permission(PAY)),
):
    await _owned(db, booking_id, transaction_id)
    return await MpesaService(db, client=client).refresh_from_daraja(transaction_id)


@router.post("/integrations/mpesa/callback", dependencies=[_callback_limit])
async def mpesa_callback(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()
    try:
        result = parse_stk_callback(payload)
    except Exception:  # noqa: BLE001 — a malformed callback is not our bug to raise on
        return {"ResultCode": 0, "ResultDesc": "Accepted"}

    await MpesaService(db).settle(result, today=datetime.now(UTC).date())
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
