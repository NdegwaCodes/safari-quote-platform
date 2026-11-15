from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CommunicationLog(BaseModel):

    channel: str | None = Field(default=None, max_length=40)
    direction: str
    occurred_at: datetime | None = None
    subject_line: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1)
    reached: bool | None = None
    duration_minutes: int | None = Field(default=None, ge=1)
    external_ref: str | None = Field(default=None, max_length=200)

    next_action_on: date | None = None
    next_action_note: str | None = None


class CommunicationAmend(BaseModel):

    subject_line: str | None = Field(default=None, max_length=200)
    body: str | None = Field(default=None, min_length=1)
    occurred_at: datetime | None = None
    reached: bool | None = None
    duration_minutes: int | None = Field(default=None, ge=1)
    external_ref: str | None = Field(default=None, max_length=200)


class CommunicationVoid(BaseModel):
    reason: str = Field(min_length=1)


class CommunicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    subject: str
    subject_id: uuid.UUID
    channel: str
    direction: str
    occurred_at: datetime
    subject_line: str | None
    body: str
    reached: bool | None
    duration_minutes: int | None
    external_ref: str | None
    logged_by: uuid.UUID | None
    amended_at: datetime | None
    amended_by: uuid.UUID | None
    voided_at: datetime | None
    voided_by: uuid.UUID | None
    void_reason: str | None
    created_at: datetime


class ContactedRead(BaseModel):

    entries: int
    contacts: int
    last_contact_at: datetime | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    chases: int = 0
    by_channel: dict[str, int] = Field(default_factory=dict)
    by_direction: dict[str, int] = Field(default_factory=dict)
    unreached_calls: int = 0


class SilenceRead(BaseModel):

    chases: int
    days: int
    since: datetime
    ever_replied: bool
    message: str


class TimelineRead(BaseModel):

    subject: str
    subject_id: uuid.UUID
    entries: list[CommunicationRead]
    summary: ContactedRead
    first_response_hours: Decimal | None = None
    gone_quiet: SilenceRead | None = None
