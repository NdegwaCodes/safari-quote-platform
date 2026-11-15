from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.db.seed_demo import seed_demo
from app.db.session import AsyncSessionLocal
from app.main import app
from app.modules.accommodations.models import (
    Accommodation,
    AccommodationRate,
    MealPlan,
    RoomType,
)
from app.modules.destinations.models import Destination
from app.modules.quotes.models import Quote, QuoteOption, QuoteOptionLeg
from app.modules.residence.models import ResidenceCategory


def _refuse_non_test_database() -> None:
    url = settings.sqlalchemy_database_uri or ""
    name = url.rsplit("/", 1)[-1].split("?")[0]
    if not name.endswith("_test"):
        raise RuntimeError(
            f"REFUSING to run tests against database {name!r} — the name does "
            "not end in '_test'. This suite seeds, mutates and deletes rows.\n"
            "Run `bash scripts/test_local.sh`, which points DATABASE_URL at a "
            "throwaway database, rather than pytest directly."
        )


_refuse_non_test_database()


@pytest_asyncio.fixture(loop_scope="session")
async def client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(loop_scope="session")
async def admin_tokens(client: AsyncClient) -> dict[str, str]:
    resp = await client.post(
        f"{settings.API_V1_STR}/auth/login",
        data={
            "username": settings.FIRST_SUPERUSER_EMAIL,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def sample_catalogue() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        return await seed_demo(db)


@pytest_asyncio.fixture(loop_scope="session")
async def restore_pricing_config(
    client: AsyncClient, admin_tokens: dict[str, str]
) -> AsyncGenerator[None, None]:
    url = f"{settings.API_V1_STR}/pricing-config"
    headers = auth_headers(admin_tokens)
    before = (await client.get(url, headers=headers)).json()
    try:
        yield
    finally:
        await client.patch(url, headers=headers, json=before)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}+{uuid.uuid4().hex[:10]}@example.com"


def auth_headers(tokens: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


D = Decimal
SEASON_FROM, SEASON_TO = date(2026, 1, 1), date(2035, 12, 31)
LODGE_TWIN = D("18000")


@pytest_asyncio.fixture(loop_scope="session")
async def upcountry_lodge():
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        fb = (
            await db.execute(select(MealPlan).where(MealPlan.code == "FB"))
        ).scalar_one()
        bb = (
            await db.execute(select(MealPlan).where(MealPlan.code == "BB"))
        ).scalar_one()
        citizen = (
            await db.execute(
                select(ResidenceCategory).where(ResidenceCategory.key == "citizen")
            )
        ).scalar_one()
        where = Destination(
            name=f"Package Highlands {tag}", slug=f"package-highlands-{tag}", type="park"
        )
        db.add(where)
        await db.flush()
        lodge = Accommodation(
            name=f"Highland Lodge {tag}",
            slug=f"highland-lodge-{tag}",
            destination_id=where.id,
            category="lodge",
        )
        db.add(lodge)
        await db.flush()
        room = RoomType(
            accommodation_id=lodge.id, name="Hill Twin", code="HTW", max_occupancy=2
        )
        db.add(room)
        await db.flush()
        for plan, twin in ((fb, LODGE_TWIN), (bb, LODGE_TWIN - D("4000"))):
            for occupancy, amount in ((2, twin), (1, twin * D("0.7"))):
                db.add(
                    AccommodationRate(
                        accommodation_id=lodge.id,
                        room_type_id=room.id,
                        meal_plan_id=plan.id,
                        residence_category_id=citizen.id,
                        season_name="standard",
                        occupancy=occupancy,
                        effective_from=SEASON_FROM,
                        effective_to=SEASON_TO,
                        currency="KES",
                        rate_per_night=amount,
                        rate_kind="sto",
                    )
                )
        bare = Accommodation(
            name=f"Rateless Camp {tag}",
            slug=f"rateless-camp-{tag}",
            destination_id=where.id,
            category="camp",
        )
        db.add(bare)
        await db.flush()
        await db.commit()
        ids = {
            "destination_id": str(where.id),
            "accommodation_id": str(lodge.id),
            "rateless_id": str(bare.id),
            "meal_plan_fb": str(fb.id),
            "meal_plan_bb": str(bb.id),
        }

    yield ids

    async with AsyncSessionLocal() as db:
        mine = [uuid.UUID(ids["accommodation_id"]), uuid.UUID(ids["rateless_id"])]
        via_option = (
            await db.execute(
                select(QuoteOption.quote_id).where(
                    QuoteOption.accommodation_id.in_(mine)
                )
            )
        ).scalars().all()
        via_leg = (
            await db.execute(
                select(QuoteOption.quote_id)
                .join(QuoteOptionLeg, QuoteOptionLeg.quote_option_id == QuoteOption.id)
                .where(QuoteOptionLeg.accommodation_id.in_(mine))
            )
        ).scalars().all()
        for quote_id in set(via_option) | set(via_leg):
            row = await db.get(Quote, quote_id)
            if row is not None:
                await db.delete(row)
        await db.flush()
        for key in ("accommodation_id", "rateless_id"):
            row = await db.get(Accommodation, uuid.UUID(ids[key]))
            if row is not None:
                await db.delete(row)
        await db.flush()
        where_row = await db.get(Destination, uuid.UUID(ids["destination_id"]))
        if where_row is not None:
            await db.delete(where_row)
        await db.commit()
