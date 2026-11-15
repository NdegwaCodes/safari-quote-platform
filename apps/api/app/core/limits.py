from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Request

from app.core.errors import AppError
from app.core.redis import redis_client

logger = logging.getLogger("acacia.limits")


class TooManyRequests(AppError):

    status_code = 429
    code = "RATE_LIMITED"


@dataclass(frozen=True)
class Window:

    limit: int
    seconds: int

    def __post_init__(self) -> None:
        if self.limit < 1 or self.seconds < 1:
            raise ValueError("A window needs a positive limit and duration.")


def caller(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def spend(key: str, window: Window) -> int:
    try:
        count = int(await redis_client.incr(key))
        if count == 1:
            await redis_client.expire(key, window.seconds)
        ttl = int(await redis_client.ttl(key))
    except Exception:  # noqa: BLE001 - see the module docstring on failing open
        logger.warning("Rate limiter unavailable; allowing %s", key, exc_info=True)
        return 0

    if count > window.limit:
        wait = max(ttl, 1)
        raise TooManyRequests(
            f"Too many requests. Please try again in {wait} second(s)."
        )
    return count


def rate_limit(
    *, bucket: str, limit: int, seconds: int
) -> Callable[..., Awaitable[None]]:
    window = Window(limit=limit, seconds=seconds)

    async def _guard(who: str = Depends(caller)) -> None:
        await spend(f"ratelimit:{bucket}:{who}", window)

    return _guard


__all__ = ["TooManyRequests", "Window", "caller", "rate_limit", "spend"]
