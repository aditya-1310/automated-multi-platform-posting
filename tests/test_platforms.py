"""Adapter tests. Every outbound HTTP call is mocked with respx; unmocked calls fail the test."""

import json
from datetime import datetime, timezone

import httpx
import pytest

from app.platforms import build_platforms
from app.platforms.base import PlatformError, PublishedPost
from app.platforms.bluesky import BlueskyPlatform, link_facet
from app.platforms.devto import DevToPlatform
from app.platforms.discord import DiscordPlatform
from app.platforms.github_gist import GitHubGistPlatform
from app.platforms.huggingface import HuggingFacePlatform
from app.platforms.mastodon import MastodonPlatform
from app.platforms.telegram import TelegramPlatform
from app.services.posting_service import PostingService

LINK = "https://example.com"
MESSAGE = f"Grow your online visibility today {LINK}"


def body(route, index=-1) -> dict:
    return json.loads(route.calls[index].request.content)


# ---------- registry ----------


def test_registry_order_is_fixed(settings, client):
    names = [p.name for p in build_platforms(settings, client)]
    assert names == ["Telegram", "Mastodon", "GitHub Gist", "Bluesky", "DEV.to", "Hugging Face", "Discord"]


def test_empty_settings_report_missing_variables(client):
    from app.config import Settings

    platforms = build_platforms(Settings(_env_file=None), client)
    telegram = platforms[0]
    assert telegram.missing_settings() == ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL"]


# ---------- Telegram ----------

TG_SEND = "https://api.telegram.org/bot123456:tg-secret-token/sendMessage"


async def test_telegram_publish(settings, client, respx_mock):
    route = respx_mock.post(TG_SEND).respond(
        json={"ok": True, "result": {"message_id": 42, "date": 1794830400}}
    )
    post = await TelegramPlatform(settings, client).publish(MESSAGE, LINK)

    assert body(route) == {"chat_id": "@mychannel", "text": MESSAGE}  # no parse_mode
    assert post.url == "https://t.me/mychannel/42"
    assert post.created_at == datetime.fromtimestamp(1794830400, tz=timezone.utc)


async def test_telegram_error_is_readable(settings, client, respx_mock):
    respx_mock.post(TG_SEND).respond(400, json={"ok": False, "description": "Bad Request: chat not found"})
    with pytest.raises(PlatformError, match=r"Platform error \(HTTP 400\): Bad Request: chat not found"):
        await TelegramPlatform(settings, client).publish(MESSAGE, LINK)


async def test_telegram_token_is_redacted_end_to_end(settings, client, respx_mock):
    respx_mock.post(TG_SEND).respond(400, json={"ok": False, "description": f"bad url {TG_SEND}"})
    service = PostingService([TelegramPlatform(settings, client)], platform_timeout=5, public_check_timeout=5)
    result = (await service.post_all(MESSAGE, LINK)).results[0]
    assert result.status == "failed"
    assert "tg-secret-token" not in result.error


async def test_telegram_public_check_matches_message_text(settings, client, respx_mock):
    html = (
        '<div class="tgme_widget_message_text">Grow your online visibility\ntoday '
        f'<a href="{LINK}">{LINK}</a></div>'
    )
    route = respx_mock.get("https://t.me/mychannel/42", params={"embed": "1", "mode": "tme"}).respond(text=html)
    post = PublishedPost(url="https://t.me/mychannel/42", created_at=datetime.now(timezone.utc), text=MESSAGE)

    assert await TelegramPlatform(settings, client).check_public(post) is True
    assert "authorization" not in route.calls.last.request.headers


async def test_telegram_public_check_fails_without_message_text(settings, client, respx_mock):
    respx_mock.get("https://t.me/mychannel/999", params={"embed": "1", "mode": "tme"}).respond(text="<div>Post not found</div>")
    post = PublishedPost(url="https://t.me/mychannel/999", created_at=datetime.now(timezone.utc), text=MESSAGE)
    assert await TelegramPlatform(settings, client).check_public(post) is False


# ---------- Mastodon ----------


async def test_mastodon_publish(settings, client, respx_mock):
    route = respx_mock.post("https://mastodon.example/api/v1/statuses").respond(
        json={"url": "https://mastodon.example/@me/1134", "created_at": "2026-11-16T10:30:00.000Z"}
    )
    post = await MastodonPlatform(settings, client).publish(MESSAGE, LINK)

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer masto-secret"
    assert body(route) == {"status": MESSAGE, "visibility": "public"}
    assert post.url == "https://mastodon.example/@me/1134"
    assert post.created_at == datetime(2026, 11, 16, 10, 30, tzinfo=timezone.utc)


async def test_mastodon_auth_failure(settings, client, respx_mock):
    respx_mock.post("https://mastodon.example/api/v1/statuses").respond(401, json={"error": "invalid token"})
    with pytest.raises(PlatformError, match=r"Authentication failed \(HTTP 401\)"):
        await MastodonPlatform(settings, client).publish(MESSAGE, LINK)


# ---------- GitHub Gist ----------


async def test_gist_publish(settings, client, respx_mock):
    route = respx_mock.post("https://api.github.com/gists").respond(
        201, json={"html_url": "https://gist.github.com/me/abc123", "created_at": "2026-11-16T10:30:00Z"}
    )
    post = await GitHubGistPlatform(settings, client).publish(MESSAGE, LINK)

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer gh-secret"
    assert body(route) == {
        "description": "Grow your online visibility today",
        "public": True,
        "files": {"post.md": {"content": MESSAGE}},
    }
    assert post.url == "https://gist.github.com/me/abc123"


async def test_gist_rate_limited(settings, client, respx_mock):
    respx_mock.post("https://api.github.com/gists").respond(429)
    with pytest.raises(PlatformError, match="Rate limited"):
        await GitHubGistPlatform(settings, client).publish(MESSAGE, LINK)


# ---------- Bluesky ----------

BSKY = "https://bsky.social/xrpc"
AT_URI = "at://did:plc:abc/app.bsky.feed.post/3kxyz"


def session(access="access-1", refresh="refresh-1"):
    return {"accessJwt": access, "refreshJwt": refresh, "did": "did:plc:abc", "handle": "me.bsky.social"}


def test_link_facet_uses_utf8_byte_offsets():
    text = f"\U0001F680 Launch day {LINK}"  # rocket emoji is 1 char but 4 bytes
    facet = link_facet(text, LINK)
    start = len("\U0001F680 Launch day ".encode("utf-8"))
    assert start == 16
    assert facet["index"] == {"byteStart": 16, "byteEnd": 16 + len(LINK)}
    assert facet["features"] == [{"$type": "app.bsky.richtext.facet#link", "uri": LINK}]
    assert text.encode("utf-8")[16:16 + len(LINK)].decode() == LINK


async def test_bluesky_logs_in_once_across_posts(settings, client, respx_mock):
    login = respx_mock.post(f"{BSKY}/com.atproto.server.createSession").respond(json=session())
    create = respx_mock.post(f"{BSKY}/com.atproto.repo.createRecord").respond(json={"uri": AT_URI, "cid": "c"})
    platform = BlueskyPlatform(settings, client)

    first = await platform.publish(MESSAGE, LINK)
    await platform.publish(MESSAGE, LINK)

    assert login.call_count == 1
    assert body(login) == {"identifier": "me.bsky.social", "password": "bsky-app-pass"}
    assert create.call_count == 2
    assert create.calls.last.request.headers["authorization"] == "Bearer access-1"
    payload = body(create)
    assert payload["repo"] == "did:plc:abc"
    assert payload["collection"] == "app.bsky.feed.post"
    assert payload["record"]["text"] == MESSAGE
    assert payload["record"]["facets"] == [link_facet(MESSAGE, LINK)]
    assert first.url == "https://bsky.app/profile/me.bsky.social/post/3kxyz"
    assert first.raw_id == AT_URI


async def test_bluesky_refreshes_expired_token(settings, client, respx_mock):
    login = respx_mock.post(f"{BSKY}/com.atproto.server.createSession").respond(json=session())
    refresh = respx_mock.post(f"{BSKY}/com.atproto.server.refreshSession").respond(
        json=session("access-2", "refresh-2")
    )
    create = respx_mock.post(f"{BSKY}/com.atproto.repo.createRecord")
    create.side_effect = [
        httpx.Response(400, json={"error": "ExpiredToken", "message": "Token has expired"}),
        httpx.Response(200, json={"uri": AT_URI, "cid": "c"}),
    ]

    post = await BlueskyPlatform(settings, client).publish(MESSAGE, LINK)

    assert login.call_count == 1
    assert refresh.calls.last.request.headers["authorization"] == "Bearer refresh-1"
    assert create.calls.last.request.headers["authorization"] == "Bearer access-2"
    assert post.raw_id == AT_URI


async def test_bluesky_falls_back_to_login_when_refresh_fails(settings, client, respx_mock):
    login = respx_mock.post(f"{BSKY}/com.atproto.server.createSession")
    login.side_effect = [httpx.Response(200, json=session()), httpx.Response(200, json=session("access-3"))]
    respx_mock.post(f"{BSKY}/com.atproto.server.refreshSession").respond(400, json={"error": "ExpiredToken"})
    create = respx_mock.post(f"{BSKY}/com.atproto.repo.createRecord")
    create.side_effect = [
        httpx.Response(400, json={"error": "ExpiredToken"}),
        httpx.Response(200, json={"uri": AT_URI, "cid": "c"}),
    ]

    await BlueskyPlatform(settings, client).publish(MESSAGE, LINK)

    assert login.call_count == 2
    assert create.calls.last.request.headers["authorization"] == "Bearer access-3"


async def test_bluesky_bad_password(settings, client, respx_mock):
    respx_mock.post(f"{BSKY}/com.atproto.server.createSession").respond(401, json={"error": "AuthenticationRequired"})
    with pytest.raises(PlatformError, match="Authentication failed"):
        await BlueskyPlatform(settings, client).publish(MESSAGE, LINK)


async def test_bluesky_public_check_uses_public_appview(settings, client, respx_mock):
    route = respx_mock.get(
        "https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread", params={"uri": AT_URI}
    ).respond(json={"thread": {"post": {"uri": AT_URI}}})
    post = PublishedPost(url="https://bsky.app/profile/me/post/3kxyz", created_at=datetime.now(timezone.utc),
                         raw_id=AT_URI)

    assert await BlueskyPlatform(settings, client).check_public(post) is True
    assert "authorization" not in route.calls.last.request.headers


async def test_bluesky_public_check_not_found(settings, client, respx_mock):
    respx_mock.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread", params={"uri": AT_URI}).respond(
        400, json={"error": "NotFound"}
    )
    post = PublishedPost(url="https://bsky.app/x", created_at=datetime.now(timezone.utc), raw_id=AT_URI)
    assert await BlueskyPlatform(settings, client).check_public(post) is False


# ---------- DEV.to ----------


async def test_devto_publish(settings, client, respx_mock):
    route = respx_mock.post("https://dev.to/api/articles").respond(
        201, json={"url": "https://dev.to/me/grow-1abc", "published_at": "2026-11-16T10:30:00Z"}
    )
    post = await DevToPlatform(settings, client).publish(MESSAGE, LINK)

    request = route.calls.last.request
    assert request.headers["api-key"] == "devto-secret"
    assert body(route) == {
        "article": {"title": "Grow your online visibility today", "body_markdown": MESSAGE, "published": True}
    }
    assert post.url == "https://dev.to/me/grow-1abc"


async def test_devto_validation_error(settings, client, respx_mock):
    respx_mock.post("https://dev.to/api/articles").respond(422, json={"error": "Title is too short"})
    with pytest.raises(PlatformError, match=r"HTTP 422\): Title is too short"):
        await DevToPlatform(settings, client).publish(MESSAGE, LINK)


# ---------- Hugging Face ----------


async def test_huggingface_publish_on_dataset(settings, client, respx_mock):
    route = respx_mock.post("https://huggingface.co/api/datasets/me/posts/discussions").respond(json={"num": 3})
    post = await HuggingFacePlatform(settings, client).publish(MESSAGE, LINK)

    assert route.calls.last.request.headers["authorization"] == "Bearer hf_secret"
    assert body(route) == {"title": "Grow your online visibility today", "description": MESSAGE}
    assert post.url == "https://huggingface.co/datasets/me/posts/discussions/3"


async def test_huggingface_model_repo_url_has_no_type_prefix(settings, client, respx_mock):
    settings.hf_repo_type = "model"
    respx_mock.post("https://huggingface.co/api/models/me/posts/discussions").respond(json={"num": 7})
    post = await HuggingFacePlatform(settings, client).publish(MESSAGE, LINK)
    assert post.url == "https://huggingface.co/me/posts/discussions/7"


# ---------- Discord ----------

WEBHOOK = "https://discord.com/api/webhooks/111/discord-secret-token"


async def test_discord_publish_builds_url_with_cached_guild(settings, client, respx_mock):
    info = respx_mock.get(WEBHOOK).respond(json={"id": "111", "guild_id": "999", "channel_id": "777"})
    send = respx_mock.post(WEBHOOK, params={"wait": "true"}).respond(
        json={"id": "555", "channel_id": "777", "timestamp": "2026-11-16T10:30:00.000000+00:00"}
    )
    platform = DiscordPlatform(settings, client)

    post = await platform.publish(MESSAGE, LINK)
    await platform.publish(MESSAGE, LINK)

    assert info.call_count == 1
    assert send.call_count == 2
    assert body(send) == {"content": MESSAGE, "allowed_mentions": {"parse": []}}
    assert post.url == "https://discord.com/channels/999/777/555"
    assert await platform.check_public(post) is False


def test_discord_secrets_include_webhook_token(settings, client):
    secrets = DiscordPlatform(settings, client).secrets()
    assert WEBHOOK in secrets
    assert "discord-secret-token" in secrets


# ---------- default public check (Mastodon, Gist, DEV.to, Hugging Face) ----------


@pytest.mark.parametrize("cls", [MastodonPlatform, GitHubGistPlatform, DevToPlatform, HuggingFacePlatform])
@pytest.mark.parametrize("status,expected", [(200, True), (404, False)])
async def test_default_public_check_is_anonymous(cls, status, expected, settings, client, respx_mock):
    route = respx_mock.get("https://site.example/post/1").respond(status)
    post = PublishedPost(url="https://site.example/post/1", created_at=datetime.now(timezone.utc))

    assert await cls(settings, client).check_public(post) is expected
    assert "authorization" not in route.calls.last.request.headers
    assert "api-key" not in route.calls.last.request.headers
