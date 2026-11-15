from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.quotes.models import QUOTE_STATUSES

TRAVELLER_TYPES = ("adult", "child", "infant")


class TravellerIn(BaseModel):
    traveller_type: str
    age: int | None = Field(default=None, ge=0, le=120)

    @model_validator(mode="after")
    def _check_type(self) -> TravellerIn:
        if self.traveller_type not in TRAVELLER_TYPES:
            raise ValueError(f"traveller_type must be one of {TRAVELLER_TYPES}")
        return self


class CohortIn(BaseModel):

    residence_category_id: uuid.UUID
    traveller_type: str
    headcount: int = Field(ge=1)

    @model_validator(mode="after")
    def _check_type(self) -> CohortIn:
        if self.traveller_type not in TRAVELLER_TYPES:
            raise ValueError(f"traveller_type must be one of {TRAVELLER_TYPES}")
        return self


class CohortRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    residence_category_id: uuid.UUID
    traveller_type: str
    headcount: int


class AccommodationSelectionIn(BaseModel):
    accommodation_id: uuid.UUID
    room_type_id: uuid.UUID
    meal_plan_id: uuid.UUID
    rooms: int = Field(default=1, ge=1)
    nights: int = Field(default=1, ge=1)


class ActivitySelectionIn(BaseModel):
    activity_id: uuid.UUID
    day: int | None = Field(default=None, ge=1)
    adults: int = Field(default=0, ge=0)
    children: int = Field(default=0, ge=0)


class LegIn(BaseModel):
    destination_id: uuid.UUID
    nights: int = Field(default=1, ge=1)
    check_in: date | None = None
    check_out: date | None = None
    accommodations: list[AccommodationSelectionIn] = Field(default_factory=list)
    activities: list[ActivitySelectionIn] = Field(default_factory=list)


class TransportIn(BaseModel):
    vehicle_id: uuid.UUID
    estimated_km: Decimal = Field(default=Decimal("0"), ge=0)
    days: int = Field(default=1, ge=1)


class TransportSegmentIn(BaseModel):

    sequence: int = Field(default=0, ge=0)
    kind: str = Field(max_length=20)
    mode: str = Field(max_length=10)
    travel_class: str = Field(default="", max_length=20)
    destination_id: uuid.UUID | None = None
    origin_id: uuid.UUID | None = None
    vehicle_id: uuid.UUID | None = None
    vehicle_type: str | None = Field(default=None, max_length=40)
    units: int = Field(default=1, ge=1)
    travel_date: date | None = None
    is_optional: bool = False
    is_vvip: bool = False
    description: str | None = None


class TransportSegmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sequence: int
    kind: str
    mode: str
    travel_class: str
    destination_id: uuid.UUID | None
    origin_id: uuid.UUID | None
    vehicle_id: uuid.UUID | None
    vehicle_type: str | None
    units: int
    travel_date: date | None
    is_optional: bool
    is_vvip: bool
    description: str | None


class OptionLegIn(BaseModel):

    sequence: int = Field(ge=1)
    destination_id: uuid.UUID
    accommodation_id: uuid.UUID
    check_in: date
    check_out: date
    requested_meal_plan_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check_dates(self) -> OptionLegIn:
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        return self


class OptionLegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sequence: int
    destination_id: uuid.UUID
    accommodation_id: uuid.UUID
    check_in: date
    check_out: date
    requested_meal_plan_id: uuid.UUID | None
    room_type_id: uuid.UUID | None
    meal_plan_id: uuid.UUID | None
    rooms_required: int | None
    meal_plan_fallback_from: str | None


class QuoteOptionIn(BaseModel):

    accommodation_id: uuid.UUID
    is_recommended: bool = False
    sort_order: int = 0
    agent_cover_fee: Decimal = Field(default=Decimal("0"), ge=0)
    chef_fee_per_meal: Decimal | None = Field(default=None, ge=0)
    manual_meal_cost: Decimal | None = Field(default=None, ge=0)
    is_comparable: bool = True
    notes: str | None = None
    legs: list[OptionLegIn] = Field(default_factory=list)


class QuoteCreate(BaseModel):
    client_id: uuid.UUID
    lead_id: uuid.UUID | None = None
    presentation_currency: str | None = Field(default=None, min_length=3, max_length=3)
    residence_category_id: uuid.UUID | None = None
    arrival_date: date
    departure_date: date
    markup_pct: Decimal | None = Field(default=None, ge=0)
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    tax_pct: Decimal | None = Field(default=None, ge=0)
    travellers: list[TravellerIn] = Field(default_factory=list)
    cohorts: list[CohortIn] = Field(default_factory=list)
    legs: list[LegIn] = Field(default_factory=list)
    transport: list[TransportIn] = Field(default_factory=list)
    transport_segments: list[TransportSegmentIn] = Field(default_factory=list)

    pax_count: int | None = Field(default=None, ge=1)
    profit_pct: Decimal | None = Field(default=None, ge=0, le=100)
    contingency_pct: Decimal | None = Field(default=None, ge=0, le=100)
    requested_meal_plan_id: uuid.UUID | None = None
    options: list[QuoteOptionIn] = Field(default_factory=list)
    document_title: str | None = Field(default=None, max_length=160)
    document_subtitle: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _check_dates(self) -> QuoteCreate:
        if self.departure_date <= self.arrival_date:
            raise ValueError("departure_date must be after arrival_date")
        return self


class QuoteUpdate(BaseModel):

    document_title: str | None = Field(default=None, max_length=160)
    document_subtitle: str | None = Field(default=None, max_length=240)


class QuoteStatusUpdate(BaseModel):
    status: str

    @model_validator(mode="after")
    def _check_status(self) -> QuoteStatusUpdate:
        if self.status not in QUOTE_STATUSES:
            raise ValueError(f"status must be one of {QUOTE_STATUSES}")
        return self


class TravellerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    traveller_type: str
    age: int | None


class AccommodationSelectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    accommodation_id: uuid.UUID
    room_type_id: uuid.UUID
    meal_plan_id: uuid.UUID
    rooms: int
    nights: int


class ActivitySelectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    activity_id: uuid.UUID
    day: int | None
    adults: int
    children: int


class LegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sequence: int
    destination_id: uuid.UUID
    nights: int
    check_in: date | None
    check_out: date | None
    accommodations: list[AccommodationSelectionRead]
    activities: list[ActivitySelectionRead]


class TransportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    vehicle_id: uuid.UUID
    estimated_km: Decimal
    days: int


class QuoteOptionResolvedRead(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    accommodation_id: uuid.UUID
    room_type_id: uuid.UUID | None
    meal_plan_id: uuid.UUID | None
    rooms_required: int | None
    meal_plan_fallback_from: str | None
    is_comparable: bool
    is_recommended: bool
    sort_order: int
    legs: list[OptionLegRead] = Field(default_factory=list)


class QuoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    quote_number: str
    client_id: uuid.UUID
    status: str
    presentation_currency: str
    residence_category_id: uuid.UUID
    arrival_date: date
    departure_date: date
    markup_pct: Decimal | None
    discount_pct: Decimal | None
    tax_pct: Decimal | None
    current_version_id: uuid.UUID | None
    created_at: datetime
    pax_count: int | None
    profit_pct: Decimal | None
    contingency_pct: Decimal | None
    requested_meal_plan_id: uuid.UUID | None
    lead_id: uuid.UUID | None = None
    valid_until: date | None
    effective_status: str
    decided_at: datetime | None = None
    decision_note: str | None = None
    selected_option_id: uuid.UUID | None
    selected_at: datetime | None
    travellers: list[TravellerRead]
    cohorts: list[CohortRead]
    legs: list[LegRead]
    transport: list[TransportRead]
    transport_segments: list[TransportSegmentRead]
    options: list[QuoteOptionResolvedRead]
    rejected_candidates: list[RejectedCandidateFullRead]


class QuoteSummary(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    quote_number: str
    client_id: uuid.UUID
    status: str
    presentation_currency: str
    arrival_date: date
    departure_date: date
    created_at: datetime


class CalculateRequest(BaseModel):

    residence_category_id: uuid.UUID
    presentation_currency: str = Field(min_length=3, max_length=3)
    arrival_date: date
    departure_date: date
    markup_pct: Decimal | None = Field(default=None, ge=0)
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    tax_pct: Decimal | None = Field(default=None, ge=0)
    travellers: list[TravellerIn] = Field(default_factory=list)
    legs: list[LegIn] = Field(default_factory=list)
    transport: list[TransportIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_dates(self) -> CalculateRequest:
        if self.departure_date <= self.arrival_date:
            raise ValueError("departure_date must be after arrival_date")
        return self


class PricingLineClient(BaseModel):

    category: str
    description: str
    quantity: Decimal
    client_price: Decimal


class PricingLineInternal(PricingLineClient):

    source_currency: str
    internal_cost: Decimal


class PricingResultClient(BaseModel):
    presentation_currency: str
    lines: list[PricingLineClient]
    selling_price: Decimal


class PricingResultInternal(BaseModel):
    presentation_currency: str
    lines: list[PricingLineInternal]
    markup_pct: Decimal
    discount_pct: Decimal
    tax_pct: Decimal
    internal_cost: Decimal
    selling_subtotal: Decimal
    discount_value: Decimal
    after_discount: Decimal
    tax: Decimal
    selling_price: Decimal
    gross_profit: Decimal
    gross_margin: Decimal
    needs_approval: bool


class QuoteItemClient(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    category: str
    description: str
    quantity: Decimal
    unit_price: Decimal


class QuoteItemInternal(QuoteItemClient):
    source_currency: str
    internal_cost: Decimal


class QuoteVersionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version_number: int
    currency: str
    selling_price: Decimal
    created_at: datetime


class QuoteVersionClientRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version_number: int
    currency: str
    selling_price: Decimal
    created_at: datetime
    items: list[QuoteItemClient]
    options: list[QuoteVersionOptionClientRead] = Field(default_factory=list)


class QuoteVersionInternalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version_number: int
    currency: str
    internal_cost: Decimal
    selling_price: Decimal
    gross_profit: Decimal
    gross_margin: Decimal
    created_at: datetime
    items: list[QuoteItemInternal]
    options: list[QuoteVersionOptionInternalRead] = Field(default_factory=list)


class OptionBuildUpInternal(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    cost_subtotal: Decimal
    contingency_value: Decimal
    cost_basis: Decimal
    profit_value: Decimal
    after_profit: Decimal
    agent_cover_fee: Decimal
    selling_total: Decimal
    per_person: Decimal | None
    group_total: Decimal
    components: dict[str, Decimal]


class SupplementChargeInternal(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    label: str
    kind: str
    basis: str
    amount: Decimal
    currency: str
    nights: int
    cost: Decimal


class TransportChargeInternal(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    sequence: int
    kind: str
    mode: str
    label: str
    basis: str
    units: int
    unit_amount: Decimal
    currency: str
    cost: Decimal
    is_optional: bool
    is_vvip: bool
    source: str = ""


class PricedLegRead(BaseModel):

    sequence: int
    accommodation_name: str
    room_type_name: str
    meal_plan_code: str
    rooms_required: int
    nights: int


class PricedLegInternalRead(PricedLegRead):

    meal_plan_fallback_from: str | None = None


class CohortPriceRead(BaseModel):

    residence: str
    traveller_type: str
    headcount: int
    currency: str
    per_person: Decimal
    total: Decimal


class QuoteOptionClientRead(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    accommodation_id: uuid.UUID
    accommodation_name: str
    room_type_name: str
    meal_plan_code: str
    rooms_required: int
    nights: int
    currency: str
    per_person: Decimal | None = None
    group_total: Decimal
    is_comparable: bool
    cohorts: list[CohortPriceRead] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)
    legs: Sequence[PricedLegRead] = Field(default_factory=list)
    conversions: dict[str, Decimal] = Field(default_factory=dict)


class QuoteOptionInternalRead(QuoteOptionClientRead):
    room_type_id: uuid.UUID
    meal_plan_id: uuid.UUID
    meal_plan_name: str
    meal_plan_fallback_from: str | None = None
    supplier_paid_total: Decimal
    retained_discount: Decimal
    supplements: list[SupplementChargeInternal]
    build_up: OptionBuildUpInternal
    warnings: list[str]
    legs: list[PricedLegInternalRead] = Field(default_factory=list)


class RejectedCandidateRead(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    accommodation_id: uuid.UUID | None = None
    name: str
    reason: str


class OptionPricingClientResult(BaseModel):
    options: list[QuoteOptionClientRead]
    rejected: list[RejectedCandidateRead]
    transport_named: list[str] = Field(default_factory=list)
    optional_transport_price: Decimal = Decimal(0)


class OptionPricingInternalResult(BaseModel):
    options: list[QuoteOptionInternalRead]
    rejected: list[RejectedCandidateRead]
    warnings: list[str]
    transport: list[TransportChargeInternal] = Field(default_factory=list)
    transport_optional: list[TransportChargeInternal] = Field(default_factory=list)
    transport_total: Decimal = Decimal(0)
    optional_transport_total: Decimal = Decimal(0)
    optional_transport_price: Decimal = Decimal(0)
    transport_named: list[str] = Field(default_factory=list)
    unpriced_transport: list[str] = Field(default_factory=list)


class QuoteOptionUpdate(BaseModel):

    is_recommended: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
    agent_cover_fee: Decimal | None = Field(default=None, ge=0)
    chef_fee_per_meal: Decimal | None = Field(default=None, ge=0)
    manual_meal_cost: Decimal | None = Field(default=None, ge=0)
    is_comparable: bool | None = None
    notes: str | None = None


class AcceptQuoteIn(BaseModel):

    option_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=2000)


class DeclineQuoteIn(BaseModel):

    note: str | None = Field(default=None, max_length=2000)


class ConversionRead(BaseModel):

    counts: dict[str, int]
    won: dict[str, Decimal]
    lost: dict[str, Decimal]
    outstanding: dict[str, Decimal]
    win_rate: Decimal | None = None
    median_days_to_decide: int | None = None
    recommendation_taken: int = 0
    recommendation_declined: int = 0
    recommendation_rate: Decimal | None = None


class RejectedCandidateIn(BaseModel):

    accommodation_id: uuid.UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1)
    sort_order: int | None = Field(default=None, ge=0)


class RejectedCandidateFullRead(RejectedCandidateRead):

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sort_order: int
    source: str


class ReadinessProblem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    severity: str
    code: str
    message: str


class ReadinessRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    is_ready: bool
    catered_options: int
    self_catering_options: int
    problems: list[ReadinessProblem]


class SelectOptionIn(BaseModel):
    option_id: uuid.UUID


class QuoteVersionOptionClientRead(BaseModel):

    model_config = ConfigDict(from_attributes=True)
    accommodation_id: uuid.UUID | None
    accommodation_name: str
    meal_plan_label: str | None
    rooms_required: int | None
    currency: str
    per_person: Decimal | None
    selling_total: Decimal
    is_recommended: bool
    is_comparable: bool
    sort_order: int


class QuoteVersionOptionInternalRead(QuoteVersionOptionClientRead):
    option_id: uuid.UUID | None
    cost_subtotal: Decimal
    contingency_value: Decimal
    profit_value: Decimal
    agent_cover_fee: Decimal
    supplier_paid_total: Decimal | None
    retained_discount: Decimal | None
