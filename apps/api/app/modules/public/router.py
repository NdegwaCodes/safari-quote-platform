from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.deps import require_permission
from app.core.limits import rate_limit
from app.core.storage import resolve
from app.db.session import get_db
from app.modules.public.enquiry import Submitted
from app.modules.public.schemas import (
    ContactRead,
    EnquiryCreate,
    EnquiryReceived,
    EstimateRead,
    EstimateRequest,
    ExperienceRead,
    LegEstimateRead,
    PlaceRead,
    PropertyRead,
    PublishedRead,
    PublishResult,
    ThinPageRead,
)
from app.modules.public.service import (
    DESTINATION,
    PROPERTY,
    EnquiryService,
    EstimateService,
    PublicSiteService,
    PublishService,
)
from app.modules.users.models import User

router = APIRouter(tags=["public"])

PUBLISH = "catalogue:publish"

_reads = Depends(
    rate_limit(
        bucket="public_read",
        limit=settings.PUBLIC_READ_PER_MINUTE,
        seconds=60,
    )
)
_enquiries = Depends(
    rate_limit(
        bucket="public_enquiry",
        limit=settings.PUBLIC_ENQUIRIES_PER_HOUR,
        seconds=3600,
    )
)
_estimates = Depends(
    rate_limit(
        bucket="public_estimate",
        limit=settings.PUBLIC_ESTIMATES_PER_HOUR,
        seconds=3600,
    )
)


@router.get("/public/contact", response_model=ContactRead, dependencies=[_reads])
async def public_contact(db: AsyncSession = Depends(get_db)):
    return await PublicSiteService(db).contact()


@router.get("/public/destinations", response_model=list[PlaceRead], dependencies=[_reads])
async def public_destinations(db: AsyncSession = Depends(get_db)):
    return await PublicSiteService(db).places()


@router.get("/public/destinations/{slug}", response_model=PlaceRead, dependencies=[_reads])
async def public_destination(slug: str, db: AsyncSession = Depends(get_db)):
    return await PublicSiteService(db).place(slug)


@router.get(
    "/public/accommodations", response_model=list[PropertyRead], dependencies=[_reads]
)
async def public_properties(
    destination: str | None = Query(default=None, description="Destination slug"),
    db: AsyncSession = Depends(get_db),
):
    return await PublicSiteService(db).properties(destination=destination)


@router.get(
    "/public/accommodations/{slug}", response_model=PropertyRead, dependencies=[_reads]
)
async def public_property(slug: str, db: AsyncSession = Depends(get_db)):
    return await PublicSiteService(db).property_page(slug)


@router.get(
    "/public/activities", response_model=list[ExperienceRead], dependencies=[_reads]
)
async def public_activities(
    destination: str | None = Query(default=None, description="Destination slug"),
    db: AsyncSession = Depends(get_db),
):
    return await PublicSiteService(db).experiences(destination=destination)


@router.get("/public/images/{kind}/{image_id}", dependencies=[_reads])
async def public_image(
    kind: str, image_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    image = await PublicSiteService(db).image(kind, image_id)
    return FileResponse(
        resolve(image.storage_path),
        media_type=image.content_type,
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


@router.post(
    "/public/enquiries",
    response_model=EnquiryReceived,
    status_code=202,
    dependencies=[_enquiries],
)
async def submit_enquiry(body: EnquiryCreate, db: AsyncSession = Depends(get_db)):
    await EnquiryService(db).capture(
        Submitted(
            name=body.name,
            email=body.email,
            phone=body.phone,
            destination=body.destination,
            travel_from=body.travel_from,
            travel_to=body.travel_to,
            pax=body.pax,
            message=body.message,
            page=body.page,
            trap=body.trap,
        )
    )
    return EnquiryReceived()


@router.post(
    "/public/estimate",
    response_model=EstimateRead,
    dependencies=[_estimates],
)
async def estimate_trip(body: EstimateRequest, db: AsyncSession = Depends(get_db)):
    legs, combined = await EstimateService(db).price_trip(
        [(leg.destination, leg.tier, leg.nights) for leg in body.legs],
        resident=body.resident,
        adults=body.adults,
        children=body.children,
    )
    return EstimateRead(
        legs=[
            LegEstimateRead(
                destination=leg.destination,
                tier=leg.tier,
                nights=leg.nights,
                property_name=leg.property_name,
                room_type=leg.room_type,
                meal_plan=leg.meal_plan,
                currency=leg.currency,
                per_person=leg.per_person,
                group_total=leg.group_total,
                refused=leg.refused.message if leg.refused else None,
            )
            for leg in legs
        ],
        currency=combined.currency,
        per_person=combined.per_person,
        group_total=combined.group_total,
    )


@router.post("/catalogue/{kind}/{row_id}/publish", response_model=PublishResult)
async def publish(
    kind: str,
    row_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(PUBLISH)),
):
    row, concerns = await PublishService(db).publish(kind, row_id, actor_id=actor.id)
    return PublishResult(
        **PublishedRead.model_validate(row).model_dump(),
        concerns=[{"code": one.code, "message": one.message} for one in concerns],
    )


@router.post("/catalogue/{kind}/{row_id}/withdraw", response_model=PublishedRead)
async def withdraw(
    kind: str,
    row_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(PUBLISH)),
):
    return await PublishService(db).withdraw(kind, row_id)


@router.get("/catalogue/{kind}/thin-pages", response_model=list[ThinPageRead])
async def thin_pages(
    kind: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_permission(PUBLISH)),
):
    found = await PublishService(db).review(kind)
    return [
        ThinPageRead(
            id=row.id,
            name=row.name,
            slug=row.slug,
            concerns=[{"code": one.code, "message": one.message} for one in concerns],
        )
        for row, concerns in found
    ]


__all__ = ["router", "PUBLISH", "DESTINATION", "PROPERTY"]
