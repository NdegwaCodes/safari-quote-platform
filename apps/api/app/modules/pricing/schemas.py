from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.pricing.config import PeakPeriodConfig


class PricingConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_markup_pct: Decimal
    default_tax_pct: Decimal
    default_discount_pct: Decimal
    discount_approval_threshold_pct: Decimal
    max_discount_pct: Decimal
    quote_validity_days: int

    contingency_pct: Decimal
    profit_pct: Decimal
    per_person_rounding: Decimal
    per_person_rounding_by_currency: dict[str, Decimal]
    quotation_validity_days: int
    min_catered_options: int
    max_catered_options: int
    min_self_catering_options: int
    max_self_catering_options: int
    max_drive_minutes_per_day: int
    default_chef_fee_per_day: Decimal
    default_chef_covers: int
    deposit_pct: Decimal
    balance_due_days_before_travel: int
    cancellation_tier1_days: int
    cancellation_tier2_days: int
    cancellation_tier2_pct: Decimal
    cancellation_tier3_days: int
    cancellation_tier3_pct: Decimal
    cancellation_forfeit_pct: Decimal
    cancellation_group_pax_threshold: int
    cancellation_group_notice_extension_days: int
    cancellation_peak_periods: list[PeakPeriodConfig]


class PricingConfigUpdate(BaseModel):

    default_markup_pct: Decimal | None = Field(default=None, ge=0)
    default_tax_pct: Decimal | None = Field(default=None, ge=0)
    default_discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    discount_approval_threshold_pct: Decimal | None = Field(default=None, ge=0, le=100)
    max_discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    quote_validity_days: int | None = Field(default=None, ge=1)
    contingency_pct: Decimal | None = Field(default=None, ge=0, le=100)
    profit_pct: Decimal | None = Field(default=None, ge=0, le=100)
    per_person_rounding: Decimal | None = Field(default=None, gt=0)
    per_person_rounding_by_currency: dict[str, Decimal] | None = None
    quotation_validity_days: int | None = Field(default=None, ge=1)
    min_catered_options: int | None = Field(default=None, ge=1)
    max_catered_options: int | None = Field(default=None, ge=1)
    min_self_catering_options: int | None = Field(default=None, ge=0)
    max_self_catering_options: int | None = Field(default=None, ge=0)
    max_drive_minutes_per_day: int | None = Field(default=None, ge=60)
    default_chef_fee_per_day: Decimal | None = Field(default=None, ge=0)
    default_chef_covers: int | None = Field(default=None, ge=1)
    deposit_pct: Decimal | None = Field(default=None, gt=0, le=100)
    balance_due_days_before_travel: int | None = Field(default=None, ge=0)
    cancellation_tier1_days: int | None = Field(default=None, ge=0)
    cancellation_tier2_days: int | None = Field(default=None, ge=0)
    cancellation_tier2_pct: Decimal | None = Field(default=None, ge=0, le=100)
    cancellation_tier3_days: int | None = Field(default=None, ge=0)
    cancellation_tier3_pct: Decimal | None = Field(default=None, ge=0, le=100)
    cancellation_forfeit_pct: Decimal | None = Field(default=None, ge=0, le=100)
    cancellation_group_pax_threshold: int | None = Field(default=None, ge=1)
    cancellation_group_notice_extension_days: int | None = Field(default=None, ge=0)
    cancellation_peak_periods: list[PeakPeriodConfig] | None = None


class ConversionRead(BaseModel):

    amount: Decimal
    from_currency: str
    to_currency: str
    on_date: str
    rate: Decimal
    converted: Decimal
