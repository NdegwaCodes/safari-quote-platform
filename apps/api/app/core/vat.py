from __future__ import annotations

from decimal import Decimal

DEFAULT_VAT_PCT = Decimal("16")


def to_vat_inclusive(
    amount: Decimal, *, vat_inclusive: bool, vat_pct: Decimal
) -> Decimal:
    if vat_inclusive:
        return amount
    if vat_pct < 0:
        raise ValueError("VAT percentage cannot be negative")
    return amount * (Decimal(1) + vat_pct / Decimal(100))
