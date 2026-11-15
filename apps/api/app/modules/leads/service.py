from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.modules.comms.rules import first_response_hours, history
from app.modules.comms.service import CommsService
from app.modules.leads.models import COMMON_SOURCES, Lead, LeadStage, LeadStageEvent
from app.modules.leads.pipeline import (
    NEVER_CONTACTED,
    NO_NEXT_ACTION,
    Attention,
    Counted,
    Pipeline,
    Stage,
    StageRefused,
    Watched,
    attention,
    check_move,
    check_pipeline,
    next_action_default,
    summarise,
)
from app.modules.quotes.models import Quote
from app.modules.quotes.outcomes import ACCEPTED

DEFAULT_STAGES: tuple[tuple[str, str, int, bool, bool, bool], ...] = (
    ("new", "New enquiry", 10, True, False, False),
    ("qualified", "Qualified", 20, False, False, False),
    ("quoted", "Quoted", 30, False, False, False),
    ("negotiating", "Negotiating", 40, False, False, False),
    ("won", "Won", 50, False, True, False),
    ("lost", "Lost", 60, False, False, True),
)


def normalise_source(value: str | None) -> str:
    cleaned = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return cleaned or "other"


class LeadService:
    def __init__(self, db: AsyncSession):
        self.db = db


    async def stages(self) -> list[LeadStage]:
        rows = list(
            (
                await self.db.execute(
                    select(LeadStage).order_by(LeadStage.sort_order)
                )
            )
            .scalars()
            .all()
        )
        if rows:
            return rows
        for key, name, order, default, won, lost in DEFAULT_STAGES:
            self.db.add(
                LeadStage(
                    key=key,
                    name=name,
                    sort_order=order,
                    is_default=default,
                    is_won=won,
                    is_lost=lost,
                )
            )
        await self.db.commit()
        return list(
            (
                await self.db.execute(
                    select(LeadStage).order_by(LeadStage.sort_order)
                )
            )
            .scalars()
            .all()
        )

    async def rename_stage(
        self,
        stage_id: uuid.UUID,
        *,
        name: str | None = None,
        sort_order: int | None = None,
        description: str | None = None,
    ) -> LeadStage:
        row = await self.db.get(LeadStage, stage_id)
        if row is None:
            raise NotFoundError("Lead stage not found.")
        if name is not None:
            row.name = name
        if sort_order is not None:
            row.sort_order = sort_order
        if description is not None:
            row.description = description
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def pipeline_problems(self) -> list[str]:
        return check_pipeline([_stage(row) for row in await self.stages()])


    async def create(
        self,
        *,
        contact_name: str,
        source: str | None = None,
        source_detail: str | None = None,
        client_id: uuid.UUID | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        owner_id: uuid.UUID | None = None,
        stage_id: uuid.UUID | None = None,
        destination_interest: str | None = None,
        travel_from: date | None = None,
        travel_to: date | None = None,
        pax_estimate: int | None = None,
        budget_amount=None,
        budget_currency: str | None = None,
        next_action_on: date | None = None,
        next_action_note: str | None = None,
        notes: str | None = None,
        actor_id: uuid.UUID | None = None,
        today: date | None = None,
    ) -> Lead:
        stages = await self.stages()
        if stage_id is not None:
            landing = next((row for row in stages if row.id == stage_id), None)
            if landing is None:
                raise NotFoundError("Lead stage not found.")
        else:
            landing = next((row for row in stages if row.is_default), None)
            if landing is None:
                raise AppError(
                    "No stage is marked as the one new enquiries arrive at, so "
                    "there is nowhere to put this lead. Set one on the pipeline."
                )
        if travel_from and travel_to and travel_to < travel_from:
            raise AppError("travel_to cannot be before travel_from.")
        if (budget_amount is None) != (budget_currency is None):
            raise AppError(
                "A budget needs both an amount and a currency, or neither."
            )

        now = datetime.now(UTC)
        lead = Lead(
            source=normalise_source(source),
            source_detail=source_detail,
            client_id=client_id,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_phone=contact_phone,
            stage_id=landing.id,
            stage_since=now,
            owner_id=owner_id,
            destination_interest=destination_interest,
            travel_from=travel_from,
            travel_to=travel_to,
            pax_estimate=pax_estimate,
            budget_amount=budget_amount,
            budget_currency=(budget_currency or "").upper() or None,
            next_action_on=next_action_on
            or next_action_default(today=today or date.today()),
            next_action_note=next_action_note,
            notes=notes,
        )
        self.db.add(lead)
        await self.db.flush()
        self.db.add(
            LeadStageEvent(
                lead_id=lead.id,
                from_stage_id=None,
                to_stage_id=landing.id,
                at=now,
                by=actor_id,
                note="Enquiry received.",
            )
        )
        await self.db.commit()
        return await self.get(lead.id)

    async def get(self, lead_id: uuid.UUID) -> Lead:
        lead = (
            await self.db.execute(select(Lead).where(Lead.id == lead_id))
        ).scalar_one_or_none()
        if lead is None:
            raise NotFoundError("Lead not found.")
        return lead

    async def update(self, lead_id: uuid.UUID, data: dict) -> Lead:
        lead = await self.get(lead_id)
        if "source" in data and data["source"] is not None:
            data["source"] = normalise_source(data["source"])
        if "budget_currency" in data and data["budget_currency"]:
            data["budget_currency"] = data["budget_currency"].upper()
        merged_from = data.get("travel_from", lead.travel_from)
        merged_to = data.get("travel_to", lead.travel_to)
        if merged_from and merged_to and merged_to < merged_from:
            raise AppError("travel_to cannot be before travel_from.")
        for field, value in data.items():
            setattr(lead, field, value)
        if (lead.budget_amount is None) != (lead.budget_currency is None):
            raise AppError(
                "A budget needs both an amount and a currency, or neither."
            )
        await self.db.commit()
        return await self.get(lead_id)

    async def move(
        self,
        lead_id: uuid.UUID,
        *,
        stage_id: uuid.UUID,
        actor_id: uuid.UUID | None = None,
        note: str | None = None,
        lost_reason: str | None = None,
        next_action_on: date | None = None,
        next_action_note: str | None = None,
    ) -> Lead:
        lead = await self.get(lead_id)
        target = await self.db.get(LeadStage, stage_id)
        if target is None:
            raise NotFoundError("Lead stage not found.")
        current = await self.db.get(LeadStage, lead.stage_id)
        try:
            check_move(
                _stage(current) if current else _stage(target),
                _stage(target),
                lost_reason=lost_reason or lead.lost_reason,
            )
        except StageRefused as exc:
            raise AppError(str(exc)) from exc

        now = datetime.now(UTC)
        self.db.add(
            LeadStageEvent(
                lead_id=lead.id,
                from_stage_id=lead.stage_id,
                to_stage_id=target.id,
                at=now,
                by=actor_id,
                note=note,
            )
        )
        lead.stage_id = target.id
        lead.stage_since = now
        if lost_reason:
            lead.lost_reason = lost_reason
        if target.is_won or target.is_lost:
            lead.next_action_on = None
            lead.next_action_note = None
        else:
            if next_action_on is not None:
                lead.next_action_on = next_action_on
            if next_action_note is not None:
                lead.next_action_note = next_action_note
        await self.db.commit()
        return await self.get(lead_id)


    async def needs_attention(
        self,
        *,
        owner_id: uuid.UUID | None = None,
        stale_after_days: int = 14,
        chase_threshold: int = 3,
        today: date | None = None,
    ) -> list[tuple[Lead, list[Attention]]]:
        when = today or date.today()
        stmt = select(Lead).join(LeadStage, LeadStage.id == Lead.stage_id).where(
            LeadStage.is_won.is_(False), LeadStage.is_lost.is_(False)
        )
        if owner_id is not None:
            stmt = stmt.where(Lead.owner_id == owner_id)
        leads = list((await self.db.execute(stmt)).scalars().all())
        logged = await CommsService(self.db).contacts_for_leads(
            [lead.id for lead in leads]
        )

        out: list[tuple[Lead, list[Attention]]] = []
        for lead in leads:
            stage = await self.db.get(LeadStage, lead.stage_id)
            log = history(logged.get(lead.id, []))
            found = attention(
                Watched(
                    name=lead.contact_name,
                    stage=_stage(stage) if stage else _stage(None),
                    stage_since=lead.stage_since.date() if lead.stage_since else None,
                    next_action_on=lead.next_action_on,
                    owner=str(lead.owner_id) if lead.owner_id else None,
                    last_contact_on=(
                        log.last_contact_at.date() if log.last_contact_at else None
                    ),
                    last_inbound_on=(
                        log.last_inbound_at.date() if log.last_inbound_at else None
                    ),
                    last_answered_on=(
                        log.last_outbound_at.date() if log.last_outbound_at else None
                    ),
                    chases=log.chases,
                    logged=log.entries,
                ),
                today=when,
                stale_after_days=stale_after_days,
                chase_threshold=chase_threshold,
            )
            if found:
                out.append((lead, found))
        out.sort(key=lambda pair: (-max(one.days for one in pair[1]), pair[0].contact_name))
        out.sort(key=lambda pair: _rank(pair[1]))
        return out

    async def summary(self, *, today: date | None = None) -> Pipeline:
        stages = await self.stages()
        by_id = {row.id: row for row in stages}
        leads = list((await self.db.execute(select(Lead))).scalars().all())

        quoted: dict[uuid.UUID, int] = {
            lead_id: int(count)
            for lead_id, count in (
                await self.db.execute(
                    select(Quote.lead_id, func.count())
                    .where(Quote.lead_id.is_not(None))
                    .group_by(Quote.lead_id)
                )
            ).all()
            if lead_id is not None
        }
        accepted = set(
            (
                await self.db.execute(
                    select(Quote.lead_id).where(
                        Quote.lead_id.is_not(None), Quote.status == ACCEPTED
                    )
                )
            )
            .scalars()
            .all()
        )

        logged = await CommsService(self.db).contacts_for_leads(
            [lead.id for lead in leads]
        )
        counted = [
            Counted(
                stage=_stage(by_id.get(lead.stage_id)),
                source=lead.source,
                stage_since=lead.stage_since.date() if lead.stage_since else None,
                budget_amount=lead.budget_amount,
                budget_currency=lead.budget_currency,
                quotes=int(quoted.get(lead.id, 0)),
                accepted=lead.id in accepted,
                first_response_hours=first_response_hours(
                    lead.created_at, logged.get(lead.id, [])
                ),
            )
            for lead in leads
        ]
        return summarise(
            counted, [_stage(row) for row in stages], today=today or date.today()
        )


def _rank(found: list[Attention]) -> int:
    codes = {one.code for one in found}
    if NEVER_CONTACTED in codes:
        return 0
    if NO_NEXT_ACTION in codes:
        return 1
    return 2


def _stage(row: LeadStage | None) -> Stage:
    if row is None:
        return Stage(key="unknown", name="Unknown")
    return Stage(
        key=row.key,
        name=row.name,
        sort_order=row.sort_order,
        is_default=row.is_default,
        is_won=row.is_won,
        is_lost=row.is_lost,
    )


__all__ = ["COMMON_SOURCES", "LeadService", "normalise_source", "DEFAULT_STAGES"]
