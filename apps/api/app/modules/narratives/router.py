from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_permission
from app.db.session import get_db
from app.integrations.narrative import ACCOMMODATION, DESTINATION
from app.modules.narratives.schemas import (
    NarrativeCompose,
    NarrativeGenerate,
    NarrativeRead,
    NarrativeReview,
    NarrativeRevise,
)
from app.modules.narratives.service import NarrativeService
from app.modules.users.models import User

router = APIRouter(tags=["narratives"])

READ = "narrative:read"
MANAGE = "narrative:manage"
APPROVE = "narrative:approve"


@router.get(
    "/accommodations/{accommodation_id}/narratives",
    response_model=list[NarrativeRead],
)
async def list_property_narratives(
    accommodation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(READ)),
):
    return await NarrativeService(db).history(ACCOMMODATION, accommodation_id)


@router.get(
    "/destinations/{destination_id}/narratives", response_model=list[NarrativeRead]
)
async def list_destination_narratives(
    destination_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(READ)),
):
    return await NarrativeService(db).history(DESTINATION, destination_id)


@router.post(
    "/accommodations/{accommodation_id}/narratives/generate",
    response_model=NarrativeRead,
    status_code=201,
)
async def generate_property_narrative(
    accommodation_id: uuid.UUID,
    body: NarrativeGenerate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE)),
):
    return await NarrativeService(db).generate(
        ACCOMMODATION,
        accommodation_id,
        actor_id=actor.id,
        steer=body.steer,
        words=body.words,
    )


@router.post(
    "/destinations/{destination_id}/narratives/generate",
    response_model=NarrativeRead,
    status_code=201,
)
async def generate_destination_narrative(
    destination_id: uuid.UUID,
    body: NarrativeGenerate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE)),
):
    return await NarrativeService(db).generate(
        DESTINATION,
        destination_id,
        actor_id=actor.id,
        steer=body.steer,
        words=body.words,
    )


@router.post(
    "/accommodations/{accommodation_id}/narratives",
    response_model=NarrativeRead,
    status_code=201,
)
async def compose_property_narrative(
    accommodation_id: uuid.UUID,
    body: NarrativeCompose,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE)),
):
    return await NarrativeService(db).compose(
        ACCOMMODATION, accommodation_id, text=body.text, actor_id=actor.id
    )


@router.post(
    "/destinations/{destination_id}/narratives",
    response_model=NarrativeRead,
    status_code=201,
)
async def compose_destination_narrative(
    destination_id: uuid.UUID,
    body: NarrativeCompose,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE)),
):
    return await NarrativeService(db).compose(
        DESTINATION, destination_id, text=body.text, actor_id=actor.id
    )


@router.patch("/narratives/{narrative_id}", response_model=NarrativeRead)
async def revise_narrative(
    narrative_id: uuid.UUID,
    body: NarrativeRevise,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(MANAGE)),
):
    return await NarrativeService(db).revise(
        narrative_id, text=body.text, actor_id=actor.id
    )


@router.post("/narratives/{narrative_id}/approve", response_model=NarrativeRead)
async def approve_narrative(
    narrative_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE)),
):
    return await NarrativeService(db).approve(narrative_id, actor_id=actor.id)


@router.post("/narratives/{narrative_id}/reject", response_model=NarrativeRead)
async def reject_narrative(
    narrative_id: uuid.UUID,
    body: NarrativeReview,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(APPROVE)),
):
    return await NarrativeService(db).reject(
        narrative_id, actor_id=actor.id, note=body.note
    )


@router.get("/narratives", response_model=list[NarrativeRead])
async def list_narratives_awaiting_review(
    status: str = Query(default="draft", description="draft | approved | rejected"),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_permission(READ)),
):
    return await NarrativeService(db).awaiting(status)
