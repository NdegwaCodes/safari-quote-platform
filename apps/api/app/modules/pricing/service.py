from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.pricing.config import PRICING_SETTINGS_KEY, PricingConfig
from app.modules.settings.models import AppSetting

_HUNDRED = Decimal("100")


def _pct(value: Decimal) -> Decimal:
    return value / _HUNDRED


def apply_markup(internal_cost: Decimal, markup_pct: Decimal) -> Decimal:
    if internal_cost < 0:
        raise ValueError("internal_cost must be >= 0")
    if markup_pct < 0:
        raise ValueError("markup_pct must be >= 0")
    return internal_cost * (Decimal(1) + _pct(markup_pct))


def apply_discount(
    subtotal: Decimal,
    *,
    discount_pct: Decimal | None = None,
    discount_amount: Decimal | None = None,
) -> Decimal:
    if discount_pct is not None and discount_amount is not None:
        raise ValueError("Provide either discount_pct or discount_amount, not both.")
    if discount_pct is not None:
        if discount_pct < 0:
            raise ValueError("discount_pct must be >= 0")
        value = subtotal * _pct(discount_pct)
    elif discount_amount is not None:
        if discount_amount < 0:
            raise ValueError("discount_amount must be >= 0")
        value = discount_amount
    else:
        value = Decimal(0)
    if value < 0:
        value = Decimal(0)
    if value > subtotal:
        value = subtotal
    return value


def apply_tax(after_discount: Decimal, tax_pct: Decimal) -> Decimal:
    if tax_pct < 0:
        raise ValueError("tax_pct must be >= 0")
    return after_discount * _pct(tax_pct)


def compute_price_breakdown(
    internal_cost: Decimal,
    *,
    markup_pct: Decimal,
    discount_pct: Decimal | None = None,
    discount_amount: Decimal | None = None,
    tax_pct: Decimal = Decimal("0"),
    discount_approval_threshold_pct: Decimal | None = None,
) -> dict[str, Any]:
    selling_subtotal = apply_markup(internal_cost, markup_pct)
    discount_value = apply_discount(
        selling_subtotal, discount_pct=discount_pct, discount_amount=discount_amount
    )
    after_discount = selling_subtotal - discount_value
    tax = apply_tax(after_discount, tax_pct)
    selling_price = after_discount + tax
    gross_profit = selling_price - internal_cost
    gross_margin = (gross_profit / selling_price) if selling_price > 0 else Decimal(0)

    effective_discount_pct = (
        (discount_value / selling_subtotal * _HUNDRED)
        if selling_subtotal > 0
        else Decimal(0)
    )
    needs_approval = (
        discount_approval_threshold_pct is not None
        and effective_discount_pct >= discount_approval_threshold_pct
    )

    return {
        "internal_cost": internal_cost,
        "markup_pct": markup_pct,
        "selling_subtotal": selling_subtotal,
        "discount_value": discount_value,
        "after_discount": after_discount,
        "tax_pct": tax_pct,
        "tax": tax,
        "selling_price": selling_price,
        "gross_profit": gross_profit,
        "gross_margin": gross_margin,
        "needs_approval": needs_approval,
    }


class PricingConfigService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _row(self) -> AppSetting | None:
        stmt = select(AppSetting).where(AppSetting.key == PRICING_SETTINGS_KEY)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get(self) -> PricingConfig:
        row = await self._row()
        if row is None:
            return PricingConfig()
        return PricingConfig.model_validate(row.value)

    async def update(
        self, patch: dict[str, Any], *, updated_by: Any | None = None
    ) -> PricingConfig:
        current = await self.get()
        merged = PricingConfig.model_validate({**current.model_dump(), **patch})
        payload = merged.model_dump(mode="json")

        row = await self._row()
        if row is None:
            row = AppSetting(key=PRICING_SETTINGS_KEY, value=payload, updated_by=updated_by)
            self.db.add(row)
        else:
            row.value = payload
            row.updated_by = updated_by
        try:
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            raise ConflictError("Could not save pricing configuration.") from exc
        return merged
