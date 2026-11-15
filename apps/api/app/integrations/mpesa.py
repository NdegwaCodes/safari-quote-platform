from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from typing import Any

import httpx

from app.core.config import settings

SANDBOX_BASE_URL = "https://sandbox.safaricom.co.ke"
PRODUCTION_BASE_URL = "https://api.safaricom.co.ke"

PAYBILL = "paybill"
TILL = "till"
_TRANSACTION_TYPES = {
    PAYBILL: "CustomerPayBillOnline",
    TILL: "CustomerBuyGoodsOnline",
}

TIMESTAMP_FORMAT = "%Y%m%d%H%M%S"


class MpesaUnavailable(RuntimeError):
    pass


class MpesaError(RuntimeError):
    pass


def normalise_phone(value: str) -> str:
    digits = "".join(ch for ch in value if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif digits.startswith("254") and len(digits) == 12:
        pass
    elif len(digits) == 9:
        digits = "254" + digits

    right_length = len(digits) == 12
    right_prefix = digits.startswith("2547") or digits.startswith("2541")
    if not (right_length and right_prefix):
        raise ValueError(
            f"'{value}' does not look like a Kenyan mobile number. Expected "
            f"something like 0712345678 or +254712345678."
        )
    return digits


def stk_timestamp(now: datetime) -> str:
    return now.strftime(TIMESTAMP_FORMAT)


def stk_password(*, shortcode: str, passkey: str, timestamp: str) -> str:
    raw = f"{shortcode}{passkey}{timestamp}"
    return base64.b64encode(raw.encode("ascii")).decode("ascii")


def whole_kes(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_CEILING))


@dataclass(frozen=True)
class StkPushAccepted:

    merchant_request_id: str
    checkout_request_id: str
    customer_message: str


@dataclass(frozen=True)
class StkPushResult:

    checkout_request_id: str
    result_code: int
    result_desc: str
    amount: Decimal | None = None
    mpesa_receipt_number: str | None = None
    transaction_date: str | None = None
    phone_number: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.result_code == 0


class MpesaClient:

    def __init__(
        self,
        *,
        environment: str,
        consumer_key: str | None,
        consumer_secret: str | None,
        shortcode: str | None,
        shortcode_type: str,
        passkey: str | None,
        callback_url: str | None,
        token_cache_seconds: int = 3500,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = PRODUCTION_BASE_URL if environment == "production" else SANDBOX_BASE_URL
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.shortcode = shortcode
        self.shortcode_type = shortcode_type
        self.passkey = passkey
        self.callback_url = callback_url
        self.token_cache_seconds = token_cache_seconds
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    @property
    def is_configured(self) -> bool:
        return bool(
            self.consumer_key
            and self.consumer_secret
            and self.shortcode
            and self.passkey
            and self.callback_url
        )

    def _require_configured(self) -> None:
        if self.is_configured:
            return
        missing = [
            name
            for name, value in (
                ("MPESA_CONSUMER_KEY", self.consumer_key),
                ("MPESA_CONSUMER_SECRET", self.consumer_secret),
                ("MPESA_SHORTCODE", self.shortcode),
                ("MPESA_PASSKEY", self.passkey),
                ("MPESA_CALLBACK_BASE_URL", self.callback_url),
            )
            if not value
        ]
        raise MpesaUnavailable(
            f"M-Pesa is not configured — missing {', '.join(missing)}. The "
            f"integration is built; these are the only values left to add."
        )

    async def _access_token(self, *, now: datetime) -> str:
        if self._token and self._token_expires_at and now < self._token_expires_at:
            return self._token
        resp = await self._client.get(
            f"{self.base_url}/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            auth=(self.consumer_key or "", self.consumer_secret or ""),
        )
        if resp.status_code != 200:
            raise MpesaError(
                f"Daraja refused to issue an access token ({resp.status_code}): "
                f"{resp.text[:300]}"
            )
        body = resp.json()
        token = body.get("access_token")
        if not token:
            raise MpesaError(f"Daraja's token response had no access_token: {body}")
        self._token = token
        self._token_expires_at = now + timedelta(seconds=self.token_cache_seconds)
        return token

    async def initiate_stk_push(
        self,
        *,
        phone_number: str,
        amount: Decimal,
        account_reference: str,
        description: str,
        now: datetime,
    ) -> StkPushAccepted:
        self._require_configured()
        phone = normalise_phone(phone_number)
        timestamp = stk_timestamp(now)
        password = stk_password(
            shortcode=self.shortcode or "", passkey=self.passkey or "", timestamp=timestamp
        )
        token = await self._access_token(now=now)

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": _TRANSACTION_TYPES[self.shortcode_type],
            "Amount": whole_kes(amount),
            "PartyA": phone,
            "PartyB": self.shortcode,
            "PhoneNumber": phone,
            "CallBackURL": self.callback_url,
            "AccountReference": account_reference[:12],
            "TransactionDesc": description[:13] or "Payment",
        }
        resp = await self._client.post(
            f"{self.base_url}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        body: dict[str, Any] = resp.json() if resp.content else {}
        if resp.status_code != 200 or body.get("ResponseCode") not in ("0", 0):
            raise MpesaError(
                f"Daraja refused the STK push ({resp.status_code}): "
                f"{body.get('errorMessage') or body.get('ResponseDescription') or resp.text[:300]}"
            )
        return StkPushAccepted(
            merchant_request_id=str(body["MerchantRequestID"]),
            checkout_request_id=str(body["CheckoutRequestID"]),
            customer_message=str(body.get("CustomerMessage") or ""),
        )

    async def query_stk_push(
        self, *, checkout_request_id: str, now: datetime
    ) -> StkPushResult:
        self._require_configured()
        timestamp = stk_timestamp(now)
        password = stk_password(
            shortcode=self.shortcode or "", passkey=self.passkey or "", timestamp=timestamp
        )
        token = await self._access_token(now=now)
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }
        resp = await self._client.post(
            f"{self.base_url}/mpesa/stkpushquery/v1/query",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        body: dict[str, Any] = resp.json() if resp.content else {}
        code = body.get("ResultCode")
        if code is None:
            raise MpesaError(f"Daraja's status query had no ResultCode: {body}")
        return StkPushResult(
            checkout_request_id=checkout_request_id,
            result_code=int(code),
            result_desc=str(body.get("ResultDesc") or ""),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


def parse_stk_callback(payload: dict[str, Any]) -> StkPushResult:
    try:
        body = payload["Body"]["stkCallback"]
    except (KeyError, TypeError) as exc:
        raise MpesaError(f"Not a recognisable STK callback: {payload}") from exc

    checkout_request_id = str(body.get("CheckoutRequestID") or "")
    result_code = int(body.get("ResultCode", -1))
    result_desc = str(body.get("ResultDesc") or "")
    if not checkout_request_id:
        raise MpesaError(f"Callback had no CheckoutRequestID: {payload}")

    items = {}
    metadata = body.get("CallbackMetadata") or {}
    for item in metadata.get("Item", []):
        name = item.get("Name")
        if name:
            items[name] = item.get("Value")

    amount = items.get("Amount")
    return StkPushResult(
        checkout_request_id=checkout_request_id,
        result_code=result_code,
        result_desc=result_desc,
        amount=Decimal(str(amount)) if amount is not None else None,
        mpesa_receipt_number=(
            str(items["MpesaReceiptNumber"]) if "MpesaReceiptNumber" in items else None
        ),
        transaction_date=(
            str(items["TransactionDate"]) if "TransactionDate" in items else None
        ),
        phone_number=(str(items["PhoneNumber"]) if "PhoneNumber" in items else None),
    )


mpesa_client = MpesaClient(
    environment=settings.MPESA_ENVIRONMENT,
    consumer_key=settings.MPESA_CONSUMER_KEY,
    consumer_secret=settings.MPESA_CONSUMER_SECRET,
    shortcode=settings.MPESA_SHORTCODE,
    shortcode_type=settings.MPESA_SHORTCODE_TYPE,
    passkey=settings.MPESA_PASSKEY,
    callback_url=settings.MPESA_CALLBACK_BASE_URL,
    token_cache_seconds=settings.MPESA_TOKEN_CACHE_SECONDS,
)


async def get_mpesa_client() -> MpesaClient:
    return mpesa_client


__all__ = [
    "PAYBILL",
    "PRODUCTION_BASE_URL",
    "SANDBOX_BASE_URL",
    "TILL",
    "MpesaClient",
    "MpesaError",
    "MpesaUnavailable",
    "StkPushAccepted",
    "StkPushResult",
    "get_mpesa_client",
    "mpesa_client",
    "normalise_phone",
    "parse_stk_callback",
    "stk_password",
    "stk_timestamp",
    "whole_kes",
]
