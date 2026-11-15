from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LeadStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    key: str
    name: str
    sort_order: int
    is_default: bool
    is_won: bool
    is_lost: bool
    description: str | None = None
    is_active: bool


class LeadStageUpdate(BaseModel):

    name: str | None = Field(default=None, min_length=1, max_length=80)
    sort_order: int | None = Field(default=None, ge=0)
    description: str | None = None


class LeadBase(BaseModel):
    source: str | None = Field(default=None, max_length=40)
    source_detail: str | None = Field(default=None, max_length=160)
    client_id: uuid.UUID | None = None
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=50)
    owner_id: uuid.UUID | None = None
    destination_interest: str | None = Field(default=None, max_length=200)
    travel_from: date | None = None
    travel_to: date | None = None
    pax_estimate: int | None = Field(default=None, ge=1)
    budget_amount: Decimal | None = Field(default=None, ge=0)
    budget_currency: str | None = Field(default=None, min_length=3, max_length=3)
    next_action_on: date | None = None
    next_action_note: str | None = None
    notes: str | None = None


class LeadCreate(LeadBase):
    contact_name: str = Field(min_length=1, max_length=200)
    stage_id: uuid.UUID | None = None


class LeadUpdate(LeadBase):

    contact_name: str | None = Field(default=None, min_length=1, max_length=200)
    lost_reason: str | None = None


class LeadMove(BaseModel):
    stage_id: uuid.UUID
    note: str | None = None
    lost_reason: str | None = None
    next_action_on: date | None = None
    next_action_note: str | None = None


class LeadStageEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    from_stage_id: uuid.UUID | None
    to_stage_id: uuid.UUID
    at: datetime
    by: uuid.UUID | None
    note: str | None


class LeadRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    source: str
    source_detail: str | None
    client_id: uuid.UUID | None
    contact_name: str
    contact_email: str | None
    contact_phone: str | None
    stage_id: uuid.UUID
    stage_since: datetime
    owner_id: uuid.UUID | None
    destination_interest: str | None
    travel_from: date | None
    travel_to: date | None
    pax_estimate: int | None
    budget_amount: Decimal | None
    budget_currency: str | None
    next_action_on: date | None
    next_action_note: str | None
    lost_reason: str | None
    notes: str | None
    created_at: datetime
    events: list[LeadStageEventRead] = Field(default_factory=list)


class AttentionRead(BaseModel):
    code: str
    message: str
    days: int = 0


class LeadAttentionRead(BaseModel):

    lead: LeadRead
    reasons: list[AttentionRead]


class StageCountRead(BaseModel):
    stage: str
    name: str
    leads: int
    median_days: int | None = None


class SourceCountRead(BaseModel):
    source: str
    leads: int
    quoted: int
    won: int
    win_rate: Decimal | None = None


class PipelineRead(BaseModel):
    stages: list[StageCountRead]
    sources: list[SourceCountRead]
    median_first_response_hours: Decimal | None = None
    never_answered: int = 0
    open_budget: dict[str, Decimal]
    open_leads: int
    won_leads: int
    lost_leads: int
    win_rate: Decimal | None = None
    problems: list[str] = Field(default_factory=list)
