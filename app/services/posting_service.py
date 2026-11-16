"""Fans one message out to every platform concurrently and collects one result per platform."""

import asyncio
import logging
import time
from datetime import timezone

import httpx

from app.platforms.base import Platform, PlatformError, redact
from app.schemas import PlatformResult, PostingResponse

logger = logging.getLogger("posting")


class PostingService:
    def __init__(self, platforms: list[Platform], platform_timeout: float, public_check_timeout: float) -> None:
        self.platforms = platforms  # fixed order = response order
        self.platform_timeout = platform_timeout
        self.public_check_timeout = public_check_timeout

    async def post_all(self, message: str, link: str) -> PostingResponse:
        # _post_one never raises, so gather never sees an exception.
        results = await asyncio.gather(*(self._post_one(p, message, link) for p in self.platforms))
        return PostingResponse(success=any(r.status == "success" for r in results), results=list(results))

    async def _post_one(self, platform: Platform, message: str, link: str) -> PlatformResult:
        started = time.perf_counter()
        result = await self._attempt(platform, message, link)
        if result.error:
            result.error = redact(result.error, platform.secrets())
        logger.info(
            "platform=%s status=%s duration_ms=%d url=%s error=%s",
            result.platform, result.status, (time.perf_counter() - started) * 1000, result.posted_url, result.error,
        )
        return result

    async def _attempt(self, platform: Platform, message: str, link: str) -> PlatformResult:
        missing = platform.missing_settings()
        if missing:
            return failed(platform.name, f"Not configured: missing {', '.join(missing)}")

        try:
            post = await asyncio.wait_for(platform.publish(message, link), self.platform_timeout)
        except PlatformError as exc:
            return failed(platform.name, str(exc))
        except TimeoutError:
            # The platform may still have published; we cannot know, so we never retry.
            return failed(platform.name, f"Timed out after {self.platform_timeout:g}s")
        except httpx.TimeoutException:
            return failed(platform.name, "Platform request timed out")
        except httpx.RequestError as exc:
            return failed(platform.name, f"Connection error: {type(exc).__name__}")
        except Exception as exc:  # isolate any adapter bug from the other platforms
            logger.exception("Unexpected error from %s", platform.name)
            return failed(platform.name, f"Unexpected error: {type(exc).__name__}")

        try:
            public = await asyncio.wait_for(platform.check_public(post), self.public_check_timeout)
        except Exception as exc:
            logger.warning("Public access check failed for %s: %s", platform.name, type(exc).__name__)
            public = False

        created = post.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created = created.astimezone(timezone.utc)
        return PlatformResult(
            platform=platform.name,
            status="success",
            posted_url=post.url,
            public_access=bool(public),
            date=created.date().isoformat(),
            time=created.strftime("%H:%M:%S"),
            error=None,
        )


def failed(platform: str, error: str) -> PlatformResult:
    return PlatformResult(platform=platform, status="failed", error=error)
