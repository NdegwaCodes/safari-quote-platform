from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NarrativeGenerate(BaseModel):

    steer: str = Field(default="", max_length=500)
    words: int = Field(default=80, ge=20, le=250)


class NarrativeCompose(BaseModel):

    text: str = Field(min_length=1, max_length=4000)


class NarrativeRevise(BaseModel):

    text: str = Field(min_length=1, max_length=4000)


class NarrativeReview(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class NarrativeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    subject: str
    subject_id: uuid.UUID
    status: str
    text: str
    provider: str
    model: str | None
    brief: dict
    created_by: uuid.UUID | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    superseded_at: datetime | None
    created_at: datetime
