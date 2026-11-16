import ssl

import httpx
import pytest

from app.config import Settings

# Building an SSL context is slow (~0.3 s); share one across tests. No real network is used.
SSL_CONTEXT = ssl.create_default_context()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="123456:tg-secret-token",
        telegram_channel="@mychannel",
        mastodon_base_url="https://mastodon.example/",
        mastodon_access_token="masto-secret",
        github_token="gh-secret",
        bluesky_handle="me.bsky.social",
        bluesky_app_password="bsky-app-pass",
        devto_api_key="devto-secret",
        hf_token="hf_secret",
        hf_repo_id="me/posts",
        hf_repo_type="dataset",
        discord_webhook_url="https://discord.com/api/webhooks/111/discord-secret-token",
    )


@pytest.fixture
async def client():
    async with httpx.AsyncClient(verify=SSL_CONTEXT) as c:
        yield c
