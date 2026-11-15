from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.quotes.routing import Road, normalise_types, plain
from app.modules.transport.models import Route


class RouteService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def find(
        self,
        *,
        origin_id: uuid.UUID | None,
        destination_id: uuid.UUID | None,
        on: date,
    ) -> Road | None:
        if origin_id is None or destination_id is None:
            return None
        rows = (
            (
                await self.db.execute(
                    select(Route).where(
                        or_(
                            (Route.origin_id == origin_id)
                            & (Route.destination_id == destination_id),
                            (Route.origin_id == destination_id)
                            & (Route.destination_id == origin_id),
                        ),
                        Route.is_active.is_(True),
                        Route.effective_from <= on,
                        or_(Route.effective_to.is_(None), Route.effective_to >= on),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return None
        forward = [row for row in rows if row.origin_id == origin_id]
        chosen = max(
            forward or rows, key=lambda row: (row.effective_from, row.created_at)
        )
        return _road(chosen, reversed_lookup=chosen.origin_id != origin_id)


def _road(row: Route, *, reversed_lookup: bool) -> Road:
    return Road(
        label=row.label or "",
        distance_km=Decimal(row.distance_km),
        drive_time_minutes=int(row.drive_time_minutes),
        required_vehicle_types=normalise_types(row.required_vehicle_types),
        reversed_lookup=reversed_lookup,
        notes=row.notes or "",
        source=(
            f"routes {row.id} · {plain(Decimal(row.distance_km))} km, "
            f"{row.drive_time_minutes} min from {row.effective_from}"
            + (" (read in reverse)" if reversed_lookup else "")
        ),
    )
