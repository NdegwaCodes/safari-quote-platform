from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.public.enquiry import MAX_MESSAGE, MAX_NAME, MAX_PAX


class ImageRead(BaseModel):
    id: str
    url: str
    alt_text: str | None = None
    width: int | None = None
    height: int | None = None
    is_lead: bool = False


class PlaceRead(BaseModel):
    name: str
    slug: str
    type: str = ""
    country: str = ""
    region: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    description: str | None = None
    images: list[ImageRead] = Field(default_factory=list)
    stays: list[str] = Field(default_factory=list)
    activities: list[str] = Field(default_factory=list)


class PropertyRead(BaseModel):
    name: str
    slug: str
    category: str = ""
    star_rating: int | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    check_in_time: str | None = None
    check_out_time: str | None = None
    description: str | None = None
    destination: str = ""
    destination_slug: str = ""
    rooms: list[str] = Field(default_factory=list)
    images: list[ImageRead] = Field(default_factory=list)


class ContactRead(BaseModel):

    company_name: str
    contact_email: str
    contact_phone: str
    social_line: str


class ExperienceRead(BaseModel):
    name: str
    slug: str
    description: str | None = None
    duration_minutes: int | None = None
    destination: str = ""
    destination_slug: str = ""


class EnquiryCreate(BaseModel):

    name: str = Field(max_length=MAX_NAME)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    destination: str | None = Field(default=None, max_length=200)
    travel_from: date | None = None
    travel_to: date | None = None
    pax: int | None = Field(default=None, ge=1, le=MAX_PAX)
    message: str | None = Field(default=None, max_length=MAX_MESSAGE)
    page: str | None = Field(default=None, max_length=200)
    trap: str | None = Field(default=None, max_length=200)


class EnquiryReceived(BaseModel):

    received: bool = True
    message: str = (
        "Thank you — your enquiry has reached us and somebody will be in touch."
    )


class ConcernRead(BaseModel):
    code: str
    message: str


class PublishedRead(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    is_published: bool
    published_at: datetime | None = None
    published_by: uuid.UUID | None = None


class PublishResult(PublishedRead):

    concerns: list[ConcernRead] = Field(default_factory=list)


class ThinPageRead(BaseModel):

    id: uuid.UUID
    name: str
    slug: str
    concerns: list[ConcernRead] = Field(default_factory=list)


class LegRequest(BaseModel):
    destination: str = Field(max_length=220)
    tier: str = Field(max_length=20)
    nights: int = Field(ge=1, le=30)


class EstimateRequest(BaseModel):
    resident: bool = False
    adults: int = Field(ge=1, le=20)
    children: int = Field(default=0, ge=0, le=10)
    legs: list[LegRequest] = Field(min_length=1, max_length=6)


class LegEstimateRead(BaseModel):

    destination: str
    tier: str
    nights: int
    property_name: str | None = None
    room_type: str | None = None
    meal_plan: str | None = None
    currency: str | None = None
    per_person: Decimal | None = None
    group_total: Decimal | None = None
    refused: str | None = None


class EstimateRead(BaseModel):

    legs: list[LegEstimateRead]
    currency: str | None = None
    per_person: Decimal | None = None
    group_total: Decimal | None = None
    note: str = (
        "Indicative only, based on rates published for today rather than your "
        "actual travel dates. A consultant confirms every figure — including "
        "child pricing, transfers and park fees, none of which are in this "
        "total — before you pay anything."
    )
