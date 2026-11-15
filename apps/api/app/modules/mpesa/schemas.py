from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class StkPushCreate(BaseModel):

    phone_number: str = Field(min_length=9, max_length=13)
    amount: Decimal = Field(gt=0)
    instalment_id: uuid.UUID | None = None


class MpesaTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    booking_id: uuid.UUID
    instalment_id: uuid.UUID | None
    payment_id: uuid.UUID | None
    phone_number: str
    amount: Decimal
    status: str
    merchant_request_id: str
    checkout_request_id: str
    result_code: int | None
    result_desc: str | None
    mpesa_receipt_number: str | None
    callback_received_at: datetime | None
    created_at: datetime


class StkPushAcceptedRead(BaseModel):

    transaction_id: uuid.UUID
    customer_message: str
