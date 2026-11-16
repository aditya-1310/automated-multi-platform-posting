"""Shared adapter contract and helpers used by every platform."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import ClassVar

import httpx
from pydantic import SecretStr

from app.config import Settings


class PlatformError(Exception):
    """A platform rejected the post. The message is safe to show to the caller after redaction."""


@dataclass
class PublishedPost:
    url: str
    created_at: datetime  # converted to UTC by the service; naive values are treated as UTC
    raw_id: str | None = None  # platform-native id, e.g. a Bluesky at:// URI
    text: str = ""  # the message as posted, used by some public checks


class Platform(ABC):
    name: ClassVar[str]
    required_settings: ClassVar[tuple[str, ...]]

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self.settings = settings
        self.client = client

    def _value(self, setting: str) -> str:
        value = getattr(self.settings, setting.lower())
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        return value or ""

    def missing_settings(self) -> list[str]:
        return [name for name in self.required_settings if not self._value(name)]

    def secrets(self) -> list[str]:
        """Secret values that must never appear in logs or responses."""
        return [
            self._value(name)
            for name in self.required_settings
            if isinstance(getattr(self.settings, name.lower()), SecretStr) and self._value(name)
        ]

    @abstractmethod
    async def publish(self, message: str, link: str) -> PublishedPost:
        """Publish the message. Raise PlatformError on a platform-side failure."""

    async def check_public(self, post: PublishedPost) -> bool:
        """Anonymous GET of the posted URL. Deliberately sends no auth headers."""
        response = await self.client.get(
            post.url, follow_redirects=True, timeout=self.settings.public_check_timeout_seconds
        )
        return response.status_code == 200


def ensure_ok(response: httpx.Response) -> None:
    """Turn a non-2xx platform response into a short, readable PlatformError."""
    if response.is_success:
        return
    code = response.status_code
    if code in (401, 403):
        raise PlatformError(f"Authentication failed (HTTP {code})")
    if code == 429:
        raise PlatformError("Rate limited by platform (HTTP 429)")
    raise PlatformError(f"Platform error (HTTP {code}): {short_detail(response)}")


def short_detail(response: httpx.Response, limit: int = 200) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:limit].strip() or "no details"
    if isinstance(data, dict):
        for key in ("description", "error_description", "message", "error", "detail", "errors"):
            if data.get(key):
                return str(data[key])[:limit]
    return str(data)[:limit]


def parse_timestamp(value: object) -> datetime:
    """Parse a platform timestamp (unix seconds or ISO 8601); fall back to now in UTC."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def title_from(message: str, link: str, limit: int = 60) -> str:
    """Title for platforms that require one: the message without its link, trimmed."""
    title = re.sub(r"\s+", " ", message.replace(link, " ")).strip(" -:|,")
    if not title:
        return "New post"
    return title if len(title) <= limit else title[: limit - 3].rstrip() + "..."


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "***")
    return text
