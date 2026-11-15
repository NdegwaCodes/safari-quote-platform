from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.modules.bookings.models import Booking
from app.modules.clients.models import Client
from app.modules.comms.models import BOOKING, CLIENT, LEAD, QUOTE, SUBJECTS, Communication
from app.modules.comms.rules import (
    INTERNAL,
    OUTBOUND,
    Contact,
    Contacted,
    Logged,
    LogRefused,
    Silence,
    check_logged,
    first_response_hours,
    history,
    normalise_channel,
    normalise_direction,
    silence,
)
from app.modules.leads.models import Lead
from app.modules.quotes.models import Quote

_TABLES = {LEAD: Lead, CLIENT: Client, QUOTE: Quote, BOOKING: Booking}


def normalise_subject(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned not in SUBJECTS:
        raise AppError(
            f"'{value}' is not something a conversation can be about. Say "
            f"{', '.join(SUBJECTS)}."
        )
    return cleaned


class CommsService:
    def __init__(self, db: AsyncSession):
        self.db = db


    async def log(
        self,
        *,
        subject: str,
        subject_id: uuid.UUID,
        channel: str | None,
        direction: str,
        occurred_at: datetime | None = None,
        subject_line: str | None = None,
        body: str,
        reached: bool | None = None,
        duration_minutes: int | None = None,
        external_ref: str | None = None,
        actor_id: uuid.UUID | None = None,
        next_action_on: date | None = None,
        next_action_note: str | None = None,
    ) -> Communication:
        kind = normalise_subject(subject)
        await self._must_exist(kind, subject_id)

        now = datetime.now(UTC)
        when = occurred_at or now
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        try:
            way = normalise_direction(direction)
            entry = Logged(
                channel=normalise_channel(channel),
                direction=way,
                occurred_at=when,
                body=body,
                reached=reached,
                duration_minutes=duration_minutes,
            )
            check_logged(entry, now=now)
        except LogRefused as exc:
            raise AppError(str(exc)) from exc

        row = Communication(
            subject=kind,
            subject_id=subject_id,
            channel=entry.channel,
            direction=entry.direction,
            occurred_at=when,
            subject_line=(subject_line or "").strip() or None,
            body=body.strip(),
            reached=reached,
            duration_minutes=duration_minutes,
            external_ref=(external_ref or "").strip() or None,
            logged_by=actor_id,
        )
        self.db.add(row)
        await self.db.flush()

        lead = await self._lead_behind(kind, subject_id)
        if lead is not None:
            if entry.direction != INTERNAL:
                lead.last_contact_at = _later(lead.last_contact_at, when)
                if entry.direction != OUTBOUND:
                    lead.last_inbound_at = _later(lead.last_inbound_at, when)
            if next_action_on is not None:
                lead.next_action_on = next_action_on
                lead.next_action_note = next_action_note
            elif next_action_note is not None:
                lead.next_action_note = next_action_note

        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def amend(
        self,
        comm_id: uuid.UUID,
        data: dict,
        *,
        actor_id: uuid.UUID | None = None,
    ) -> Communication:
        row = await self.get(comm_id)
        if row.is_voided:
            raise AppError(
                "This entry has been voided, so amending it would be editing "
                "the record of a mistake. Log a new one."
            )
        allowed = {
            "subject_line",
            "body",
            "occurred_at",
            "reached",
            "duration_minutes",
            "external_ref",
        }
        if extra := sorted(set(data) - allowed):
            raise AppError(
                f"These cannot be amended on a logged conversation: "
                f"{', '.join(extra)}. Void the entry and log it again."
            )
        merged = {
            "channel": row.channel,
            "direction": row.direction,
            "occurred_at": row.occurred_at,
            "body": row.body,
            "reached": row.reached,
            "duration_minutes": row.duration_minutes,
        }
        merged.update({k: v for k, v in data.items() if k in merged})
        when = merged["occurred_at"]
        if isinstance(when, datetime) and when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
            merged["occurred_at"] = when
        try:
            check_logged(
                Logged(
                    channel=str(merged["channel"]),
                    direction=str(merged["direction"]),
                    occurred_at=when,  # type: ignore[arg-type]
                    body=str(merged["body"]),
                    reached=merged["reached"],  # type: ignore[arg-type]
                    duration_minutes=merged["duration_minutes"],  # type: ignore[arg-type]
                ),
                now=datetime.now(UTC),
            )
        except LogRefused as exc:
            raise AppError(str(exc)) from exc

        for field, value in data.items():
            setattr(row, field, merged.get(field, value))
        row.amended_at = datetime.now(UTC)
        row.amended_by = actor_id
        await self.db.commit()
        await self._restamp(row)
        await self.db.refresh(row)
        return row

    async def void(
        self,
        comm_id: uuid.UUID,
        *,
        reason: str,
        actor_id: uuid.UUID | None = None,
    ) -> Communication:
        row = await self.get(comm_id)
        if not reason.strip():
            raise AppError(
                "Say why this entry is being voided. It stays visible, and "
                "without a reason the next person reads it as true."
            )
        if row.is_voided:
            raise AppError("This entry has already been voided.")
        row.voided_at = datetime.now(UTC)
        row.voided_by = actor_id
        row.void_reason = reason.strip()
        await self.db.commit()
        await self._restamp(row)
        await self.db.refresh(row)
        return row


    async def get(self, comm_id: uuid.UUID) -> Communication:
        row = await self.db.get(Communication, comm_id)
        if row is None:
            raise NotFoundError("Communication not found.")
        return row

    async def entries(
        self, subject: str, subject_id: uuid.UUID
    ) -> list[Communication]:
        kind = normalise_subject(subject)
        return list(
            (
                await self.db.execute(
                    select(Communication)
                    .where(
                        Communication.subject == kind,
                        Communication.subject_id == subject_id,
                    )
                    .order_by(Communication.occurred_at.desc())
                )
            )
            .scalars()
            .all()
        )

    async def timeline(
        self, subject: str, subject_id: uuid.UUID
    ) -> tuple[list[Communication], Contacted]:
        kind = normalise_subject(subject)
        refs = await self._related(kind, subject_id)
        if not refs:
            return [], history([])
        clauses = [
            (Communication.subject == one_kind)
            & (Communication.subject_id.in_(list(ids)))
            for one_kind, ids in refs.items()
            if ids
        ]
        stmt = select(Communication).order_by(Communication.occurred_at.desc())
        combined = clauses[0]
        for clause in clauses[1:]:
            combined = combined | clause
        rows = list((await self.db.execute(stmt.where(combined))).scalars().all())
        return rows, history([as_contact(row) for row in rows])

    async def gone_quiet(
        self,
        subject: str,
        subject_id: uuid.UUID,
        *,
        after_chases: int = 2,
        after_days: int = 7,
    ) -> Silence | None:
        _rows, log = await self.timeline(subject, subject_id)
        return silence(
            log, now=datetime.now(UTC), after_chases=after_chases, after_days=after_days
        )

    async def response_hours(self, lead: Lead) -> Decimal | None:
        rows, _log = await self.timeline(LEAD, lead.id)
        return first_response_hours(
            lead.created_at, [as_contact(row) for row in rows]
        )

    async def contacts_for_leads(
        self, lead_ids: Iterable[uuid.UUID]
    ) -> dict[uuid.UUID, list[Contact]]:
        ids = set(lead_ids)
        if not ids:
            return {}
        owners: dict[tuple[str, uuid.UUID], uuid.UUID] = {
            (LEAD, one): one for one in ids
        }
        quotes = (
            await self.db.execute(
                select(Quote.id, Quote.lead_id).where(Quote.lead_id.in_(ids))
            )
        ).all()
        for quote_id, lead_id in quotes:
            if lead_id is not None:
                owners[(QUOTE, quote_id)] = lead_id
        quote_ids = [quote_id for quote_id, _lead in quotes]
        if quote_ids:
            bookings = (
                await self.db.execute(
                    select(Booking.id, Booking.quote_id).where(
                        Booking.quote_id.in_(quote_ids)
                    )
                )
            ).all()
            for booking_id, quote_id in bookings:
                owner = owners.get((QUOTE, quote_id))
                if owner is not None:
                    owners[(BOOKING, booking_id)] = owner

        out: dict[uuid.UUID, list[Contact]] = {one: [] for one in ids}
        rows = (
            (
                await self.db.execute(
                    select(Communication).where(
                        Communication.subject_id.in_(
                            [subject_id for _kind, subject_id in owners]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            owner = owners.get((row.subject, row.subject_id))
            if owner is not None:
                out[owner].append(as_contact(row))
        return out

    async def recompute(self, lead_id: uuid.UUID) -> Lead:
        lead = await self.db.get(Lead, lead_id)
        if lead is None:
            raise NotFoundError("Lead not found.")
        _rows, log = await self.timeline(LEAD, lead_id)
        lead.last_contact_at = log.last_contact_at
        lead.last_inbound_at = log.last_inbound_at
        await self.db.commit()
        await self.db.refresh(lead)
        return lead


    async def _must_exist(self, kind: str, subject_id: uuid.UUID) -> None:
        row = await self.db.get(_TABLES[kind], subject_id)
        if row is None:
            raise NotFoundError(f"There is no {kind} with that id to log against.")

    async def _related(
        self, kind: str, subject_id: uuid.UUID
    ) -> dict[str, set[uuid.UUID]]:
        refs: dict[str, set[uuid.UUID]] = {kind: {subject_id}}
        if kind != LEAD:
            return refs
        lead = await self.db.get(Lead, subject_id)
        if lead is None:
            return refs
        if lead.client_id:
            refs.setdefault(CLIENT, set()).add(lead.client_id)
        quote_ids = set(
            (
                await self.db.execute(
                    select(Quote.id).where(Quote.lead_id == subject_id)
                )
            )
            .scalars()
            .all()
        )
        if quote_ids:
            refs.setdefault(QUOTE, set()).update(quote_ids)
            booking_ids = set(
                (
                    await self.db.execute(
                        select(Booking.id).where(Booking.quote_id.in_(quote_ids))
                    )
                )
                .scalars()
                .all()
            )
            if booking_ids:
                refs.setdefault(BOOKING, set()).update(booking_ids)
        return refs

    async def _lead_behind(self, kind: str, subject_id: uuid.UUID) -> Lead | None:
        if kind == LEAD:
            return await self.db.get(Lead, subject_id)
        if kind == QUOTE:
            quote = await self.db.get(Quote, subject_id)
            if quote is not None and quote.lead_id:
                return await self.db.get(Lead, quote.lead_id)
            return None
        if kind == BOOKING:
            booking = await self.db.get(Booking, subject_id)
            if booking is None:
                return None
            quote = await self.db.get(Quote, booking.quote_id)
            if quote is not None and quote.lead_id:
                return await self.db.get(Lead, quote.lead_id)
            return None
        return None

    async def _restamp(self, row: Communication) -> None:
        lead = await self._lead_behind(row.subject, row.subject_id)
        if lead is not None:
            await self.recompute(lead.id)


def _later(current: datetime | None, when: datetime) -> datetime:
    return when if current is None or when > current else current


def as_contact(row: Communication) -> Contact:
    return Contact(
        channel=row.channel,
        direction=row.direction,
        occurred_at=row.occurred_at,
        reached=row.reached,
        voided=row.is_voided,
    )


__all__ = ["CommsService", "as_contact", "normalise_subject"]
