import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.platforms.base import PlatformError, PublishedPost
from app.services.posting_service import PostingService

MESSAGE = "Grow your visibility https://example.com"
LINK = "https://example.com"


class FakePlatform:
    """Duck-typed stand-in for a Platform adapter."""

    def __init__(self, name, *, publish=None, public=True, missing=(), secrets=()):
        self.name = name
        self._publish = publish
        self._public = public
        self._missing = list(missing)
        self._secrets = list(secrets)
        self.calls = 0

    def missing_settings(self):
        return self._missing

    def secrets(self):
        return self._secrets

    async def publish(self, message, link):
        self.calls += 1
        if self._publish is None:
            return PublishedPost(
                url=f"https://{self.name.lower()}.test/post/1",
                created_at=datetime(2026, 11, 16, 10, 30, 0, tzinfo=timezone.utc),
            )
        return await self._publish(message, link)

    async def check_public(self, post):
        if isinstance(self._public, Exception):
            raise self._public
        return self._public


async def raise_platform_error(*_):
    raise PlatformError("Authentication failed (HTTP 401)")


async def raise_crash(*_):
    raise RuntimeError("boom")


async def hang(*_):
    await asyncio.sleep(10)


def service(*platforms, timeout=0.2):
    return PostingService(list(platforms), platform_timeout=timeout, public_check_timeout=0.2)


async def test_all_platforms_succeed():
    response = await service(FakePlatform("A"), FakePlatform("B")).post_all(MESSAGE, LINK)
    assert response.success is True
    assert [r.status for r in response.results] == ["success", "success"]
    first = response.results[0]
    assert first.posted_url == "https://a.test/post/1"
    assert first.public_access is True
    assert (first.date, first.time, first.error) == ("2026-11-16", "10:30:00", None)


async def test_one_failure_does_not_stop_the_others():
    response = await service(
        FakePlatform("A", publish=raise_platform_error), FakePlatform("B"), FakePlatform("C", publish=raise_crash)
    ).post_all(MESSAGE, LINK)
    assert response.success is True
    a, b, c = response.results
    assert (a.status, a.error, a.posted_url, a.date, a.time) == (
        "failed", "Authentication failed (HTTP 401)", None, None, None,
    )
    assert a.public_access is False
    assert b.status == "success"
    assert (c.status, c.error) == ("failed", "Unexpected error: RuntimeError")


async def test_slow_platform_times_out_without_blocking_others():
    response = await service(FakePlatform("Slow", publish=hang), FakePlatform("Fast"), timeout=0.05).post_all(
        MESSAGE, LINK
    )
    slow, fast = response.results
    assert (slow.status, slow.error) == ("failed", "Timed out after 0.05s")
    assert fast.status == "success"


async def test_unconfigured_platform_is_reported_and_not_called():
    platform = FakePlatform("Tele", missing=["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL"])
    response = await service(platform).post_all(MESSAGE, LINK)
    assert platform.calls == 0
    result = response.results[0]
    assert (result.status, result.error) == ("failed", "Not configured: missing TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL")


async def test_all_failed_gives_success_false():
    response = await service(
        FakePlatform("A", publish=raise_platform_error), FakePlatform("B", missing=["X"])
    ).post_all(MESSAGE, LINK)
    assert response.success is False
    assert all(r.status == "failed" for r in response.results)


async def test_results_keep_registry_order():
    async def slow_publish(*_):
        await asyncio.sleep(0.05)
        return PublishedPost(url="https://first.test/1", created_at=datetime.now(timezone.utc))

    response = await service(FakePlatform("First", publish=slow_publish), FakePlatform("Second")).post_all(
        MESSAGE, LINK
    )
    assert [r.platform for r in response.results] == ["First", "Second"]


async def test_date_and_time_are_utc_from_one_datetime():
    ist = timezone(timedelta(hours=5, minutes=30))

    async def ist_publish(*_):
        return PublishedPost(url="https://x.test/1", created_at=datetime(2026, 11, 17, 2, 15, 9, tzinfo=ist))

    result = (await service(FakePlatform("X", publish=ist_publish)).post_all(MESSAGE, LINK)).results[0]
    assert (result.date, result.time) == ("2026-11-16", "20:45:09")


async def test_naive_platform_timestamp_is_treated_as_utc():
    async def naive_publish(*_):
        return PublishedPost(url="https://x.test/1", created_at=datetime(2026, 11, 16, 23, 59, 59))

    result = (await service(FakePlatform("X", publish=naive_publish)).post_all(MESSAGE, LINK)).results[0]
    assert (result.date, result.time) == ("2026-11-16", "23:59:59")


@pytest.mark.parametrize("public", [False, RuntimeError("check failed")])
async def test_failed_public_check_keeps_post_successful(public):
    result = (await service(FakePlatform("X", public=public)).post_all(MESSAGE, LINK)).results[0]
    assert result.status == "success"
    assert result.public_access is False


async def test_secrets_are_redacted_from_errors():
    async def leaky(*_):
        raise PlatformError("Platform error (HTTP 400): bad token tg-secret-123")

    result = (await service(FakePlatform("X", publish=leaky, secrets=["tg-secret-123"])).post_all(MESSAGE, LINK)).results[0]
    assert "tg-secret-123" not in result.error
    assert result.error == "Platform error (HTTP 400): bad token ***"
