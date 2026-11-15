from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.quotes.cohorts import Group, group_from_counts
from app.modules.quotes.models import Quote
from app.modules.residence.models import ResidenceCategory


async def build_group(db: AsyncSession, quote: Quote) -> Group:
    categories = await _categories(db)

    if quote.cohorts:
        counts = [
            (
                _key(categories, row.residence_category_id),
                row.traveller_type.strip().lower(),
                row.headcount,
            )
            for row in quote.cohorts
        ]
        return _build(_ordered(counts, categories), categories)

    own = _key(categories, quote.residence_category_id)

    if quote.pax_count and quote.pax_count != len(quote.travellers):
        return _build([(own, "adult", quote.pax_count)], categories)

    if quote.travellers:
        by_type: dict[str, int] = {}
        for traveller in quote.travellers:
            kind = (traveller.traveller_type or "adult").strip().lower()
            by_type[kind] = by_type.get(kind, 0) + 1
        return _build(
            [(own, kind, count) for kind, count in sorted(by_type.items())], categories
        )

    raise AppError(
        "This quote has nobody travelling on it. Set pax_count, add cohorts, or "
        "add travellers before pricing it."
    )


async def residence_ids(db: AsyncSession, keys: Iterable[str]) -> dict[str, uuid.UUID]:
    wanted = set(keys)
    rows = (
        (await db.execute(select(ResidenceCategory).where(ResidenceCategory.key.in_(wanted))))
        .scalars()
        .all()
    )
    found = {row.key: row.id for row in rows}
    if missing := sorted(wanted - set(found)):
        raise AppError(
            f"These residence categories are not in this database: {', '.join(missing)}."
        )
    return found


TRAVELLER_ORDER = ("adult", "child", "infant")


def _ordered(
    counts: list[tuple[str, str, int]],
    categories: dict[uuid.UUID, ResidenceCategory],
) -> list[tuple[str, str, int]]:
    ranks = {
        category.key: (category.sort_order, category.key)
        for category in categories.values()
    }
    def key(triple: tuple[str, str, int]) -> tuple:
        residence, traveller_type, _count = triple
        kind = (
            TRAVELLER_ORDER.index(traveller_type)
            if traveller_type in TRAVELLER_ORDER
            else len(TRAVELLER_ORDER)
        )
        return (*ranks.get(residence, (10_000, residence)), kind, traveller_type)

    return sorted(counts, key=key)


def _build(
    counts: list[tuple[str, str, int]],
    categories: dict[uuid.UUID, ResidenceCategory],
) -> Group:
    currencies = _currencies(categories)
    missing = sorted(
        {residence for residence, _type, _n in counts if not currencies.get(residence)}
    )
    if missing:
        raise AppError(
            "These residence categories have no default currency, so travellers "
            f"in them cannot be priced: {', '.join(missing)}."
        )
    return group_from_counts(counts, currencies)


async def _categories(db: AsyncSession) -> dict[uuid.UUID, ResidenceCategory]:
    rows = (await db.execute(select(ResidenceCategory))).scalars().all()
    return {row.id: row for row in rows}


def _key(categories: dict[uuid.UUID, ResidenceCategory], id_: uuid.UUID) -> str:
    category = categories.get(id_)
    if category is None:
        raise AppError(
            "This quote references a residence category that no longer exists."
        )
    return category.key


def _currencies(categories: dict[uuid.UUID, ResidenceCategory]) -> dict[str, str]:
    return {
        row.key: (row.default_currency_code or "").upper() for row in categories.values()
    }
