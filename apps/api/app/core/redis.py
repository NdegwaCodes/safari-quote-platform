from __future__ import annotations

from collections.abc import Awaitable
from typing import cast

import redis.asyncio as aioredis

from app.core.config import settings

redis_client: aioredis.Redis = aioredis.from_url(
    settings.REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
)


async def get_redis() -> aioredis.Redis:
    return redis_client


async def ping() -> bool:
    return bool(await cast(Awaitable[bool], redis_client.ping()))
