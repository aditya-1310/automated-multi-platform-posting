"""Platform registry. The tuple order is the fixed order of results in every response."""

import httpx

from app.config import Settings
from app.platforms.base import Platform
from app.platforms.bluesky import BlueskyPlatform
from app.platforms.devto import DevToPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.huggingface import HuggingFacePlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform

PLATFORM_CLASSES: tuple[type[Platform], ...] = (
    TelegramPlatform,
    MastodonPlatform,
    GitHubGistPlatform,
    BlueskyPlatform,
    DevToPlatform,
    HuggingFacePlatform,
    DiscordPlatform,
)


def build_platforms(settings: Settings, client: httpx.AsyncClient) -> list[Platform]:
    return [cls(settings, client) for cls in PLATFORM_CLASSES]
