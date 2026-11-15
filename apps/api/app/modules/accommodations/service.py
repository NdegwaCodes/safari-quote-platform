from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.core.vat import DEFAULT_VAT_PCT, to_vat_inclusive
from app.modules.accommodations.models import AccommodationRate


class AccommodationRateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_rate(
        self, accommodation_id: uuid.UUID, data: dict[str, Any]
    ) -> AccommodationRate:
        if data["effective_to"] < data["effective_from"]:
            raise AppError("effective_to must be on or after effective_from.")
        if (
            data.get("child_min_age") is not None
            and data.get("child_max_age") is not None
            and data["child_max_age"] < data["child_min_age"]
        ):
            raise AppError("child_max_age must be greater than or equal to child_min_age.")

        vat_pct = data.pop("vat_pct", DEFAULT_VAT_PCT)
        stated_inclusive = data.pop("vat_inclusive", True)
        data["rate_per_night"] = to_vat_inclusive(
            data["rate_per_night"], vat_inclusive=stated_inclusive, vat_pct=vat_pct
        )
        if data.get("child_rate") is not None:
            data["child_rate"] = to_vat_inclusive(
                data["child_rate"], vat_inclusive=stated_inclusive, vat_pct=vat_pct
            )
        if data.get("single_supplement") is not None:
            data["single_supplement"] = to_vat_inclusive(
                data["single_supplement"],
                vat_inclusive=stated_inclusive,
                vat_pct=vat_pct,
            )
        data["currency"] = str(data["currency"]).upper()

        rate = AccommodationRate(
            accommodation_id=accommodation_id,
            vat_inclusive=True,
            vat_pct=vat_pct,
            **data,
        )
        self.db.add(rate)
        await self.db.commit()
        await self.db.refresh(rate)
        return rate

    async def select_rate(
        self,
        *,
        room_type_id: uuid.UUID,
        meal_plan_id: uuid.UUID,
        residence_category_id: uuid.UUID,
        stay_date: date,
    ) -> AccommodationRate:
        stmt = (
            select(AccommodationRate)
            .where(
                AccommodationRate.room_type_id == room_type_id,
                AccommodationRate.meal_plan_id == meal_plan_id,
                AccommodationRate.residence_category_id == residence_category_id,
                AccommodationRate.is_active.is_(True),
                AccommodationRate.effective_from <= stay_date,
                AccommodationRate.effective_to >= stay_date,
            )
            .order_by(
                AccommodationRate.effective_from.desc(),
                AccommodationRate.occupancy.desc(),
            )
            .limit(1)
        )
        rate = (await self.db.execute(stmt)).scalar_one_or_none()
        if rate is None:
            raise NotFoundError(
                "No accommodation rate found for the given room type, meal plan, "
                "residence category, and date."
            )
        return rate
