from __future__ import annotations

import pytest

from app.core import limits
from app.core.limits import TooManyRequests, Window, spend


class _FakeRedis:

    def __init__(self, *, broken: bool = False):
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}
        self.broken = broken
        self.expire_calls = 0

    async def incr(self, key: str) -> int:
        if self.broken:
            raise ConnectionError("redis is down")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key: str, seconds: int) -> bool:
        self.expire_calls += 1
        self.ttls[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)


@pytest.fixture
def fake(monkeypatch):
    server = _FakeRedis()
    monkeypatch.setattr(limits, "redis_client", server)
    return server


async def test_requests_inside_the_window_are_allowed(fake):
    window = Window(limit=3, seconds=60)
    assert [await spend("k", window) for _ in range(3)] == [1, 2, 3]


async def test_one_over_the_limit_is_refused_with_how_long_to_wait(fake):
    window = Window(limit=2, seconds=60)
    await spend("k", window)
    await spend("k", window)
    with pytest.raises(TooManyRequests) as raised:
        await spend("k", window)
    assert "60 second(s)" in str(raised.value)
    assert raised.value.status_code == 429


async def test_the_expiry_is_set_once_and_not_refreshed(fake):
    window = Window(limit=10, seconds=60)
    for _ in range(5):
        await spend("k", window)
    assert fake.expire_calls == 1


async def test_callers_are_counted_separately(fake):
    window = Window(limit=1, seconds=60)
    await spend("ratelimit:enquiry:1.2.3.4", window)
    await spend("ratelimit:enquiry:5.6.7.8", window)


async def test_a_dead_redis_lets_the_request_through(monkeypatch, caplog):
    monkeypatch.setattr(limits, "redis_client", _FakeRedis(broken=True))
    assert await spend("k", Window(limit=1, seconds=60)) == 0
    assert await spend("k", Window(limit=1, seconds=60)) == 0
    assert any("Rate limiter unavailable" in one.message for one in caplog.records)


def test_a_window_must_be_a_real_window():
    with pytest.raises(ValueError):
        Window(limit=0, seconds=60)
    with pytest.raises(ValueError):
        Window(limit=5, seconds=0)
