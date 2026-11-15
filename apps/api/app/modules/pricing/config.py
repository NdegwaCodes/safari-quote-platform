from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

PRICING_SETTINGS_KEY = "pricing"


class PeakPeriodConfig(BaseModel):

    start: date
    end: date
    label: str = ""


class PricingConfig(BaseModel):

    model_config = ConfigDict(extra="ignore")

    default_markup_pct: Decimal = Field(default=Decimal("20"), ge=0)
    default_tax_pct: Decimal = Field(default=Decimal("0"), ge=0)
    default_discount_pct: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    discount_approval_threshold_pct: Decimal = Field(default=Decimal("10"), ge=0, le=100)
    max_discount_pct: Decimal = Field(default=Decimal("30"), ge=0, le=100)
    quote_validity_days: int = Field(default=14, ge=1)

    contingency_pct: Decimal = Field(default=Decimal("5"), ge=0, le=100)
    profit_pct: Decimal = Field(default=Decimal("24"), ge=0, le=100)
    per_person_rounding: Decimal = Field(default=Decimal("100"), gt=0)
    per_person_rounding_by_currency: dict[str, Decimal] = Field(
        default_factory=lambda: {
            "USD": Decimal("1"),
            "EUR": Decimal("1"),
            "GBP": Decimal("1"),
        }
    )
    quotation_validity_days: int = Field(default=30, ge=1)

    min_catered_options: int = Field(default=3, ge=1)
    max_catered_options: int = Field(default=9, ge=1)
    min_self_catering_options: int = Field(default=1, ge=0)
    max_self_catering_options: int = Field(default=2, ge=0)

    max_drive_minutes_per_day: int = Field(default=600, ge=60)

    default_chef_fee_per_day: Decimal = Field(default=Decimal("15000"), ge=0)
    default_chef_covers: int = Field(default=6, ge=1)

    deposit_pct: Decimal = Field(default=Decimal("30"), gt=0, le=100)
    balance_due_days_before_travel: int = Field(default=30, ge=0)

    cancellation_tier1_days: int = Field(default=90, ge=0)
    cancellation_tier2_days: int = Field(default=60, ge=0)
    cancellation_tier2_pct: Decimal = Field(default=Decimal("50"), ge=0, le=100)
    cancellation_tier3_days: int = Field(default=30, ge=0)
    cancellation_tier3_pct: Decimal = Field(default=Decimal("75"), ge=0, le=100)
    cancellation_forfeit_pct: Decimal = Field(default=Decimal("100"), ge=0, le=100)
    cancellation_group_pax_threshold: int = Field(default=8, ge=1)
    cancellation_group_notice_extension_days: int = Field(default=30, ge=0)
    cancellation_peak_periods: list[PeakPeriodConfig] = Field(default_factory=list)

    def rounding_for(self, currency: str) -> Decimal:
        step = self.per_person_rounding_by_currency.get(currency.upper())
        if step is None or step <= 0:
            return self.per_person_rounding
        return step
