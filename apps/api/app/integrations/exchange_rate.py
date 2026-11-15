from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol


def apply_rate(amount: Decimal, rate: Decimal) -> Decimal:
    return amount * rate


class ExchangeRateProvider(Protocol):

    async def convert(
        self,
        amount: Decimal,
        from_ccy: str,
        to_ccy: str,
        on_date: date,
    ) -> Decimal: ...
