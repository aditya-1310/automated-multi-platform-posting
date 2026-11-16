"""Bluesky (AT Protocol): create an app.bsky.feed.post record with a clickable link facet.

Docs: https://docs.bsky.app/docs/advanced-guides/posts
"""

import asyncio
from datetime import datetime, timezone

import httpx

from app.platforms.base import Platform, PublishedPost, ensure_ok

PUBLIC_APPVIEW = "https://public.api.bsky.app/xrpc"


def link_facet(text: str, link: str) -> dict:
    """Facet marking `link` as clickable. Offsets are UTF-8 byte positions, not str indexes."""
    start = len(text[: text.index(link)].encode("utf-8"))
    return {
        "index": {"byteStart": start, "byteEnd": start + len(link.encode("utf-8"))},
        "features": [{"$type": "app.bsky.richtext.facet#link", "uri": link}],
    }


def _is_expired(response: httpx.Response) -> bool:
    if response.status_code == 401:
        return True
    if response.status_code == 400:
        try:
            return response.json().get("error") == "ExpiredToken"
        except ValueError:
            return False
    return False


class BlueskyPlatform(Platform):
    name = "Bluesky"
    required_settings = ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD")

    def __init__(self, settings, client) -> None:
        super().__init__(settings, client)
        # Cached because createSession is limited to 30 calls / 5 min and 300 / day per account.
        self._session: dict | None = None
        self._lock = asyncio.Lock()

    @property
    def _xrpc(self) -> str:
        return f"{self.settings.bluesky_service.rstrip('/')}/xrpc"

    async def _login(self) -> None:
        response = await self.client.post(
            f"{self._xrpc}/com.atproto.server.createSession",
            json={"identifier": self._value("BLUESKY_HANDLE"), "password": self._value("BLUESKY_APP_PASSWORD")},
        )
        ensure_ok(response)
        self._session = response.json()

    async def _refresh(self, stale_access: str) -> None:
        async with self._lock:
            if self._session and self._session["accessJwt"] != stale_access:
                return  # another request already refreshed
            response = await self.client.post(
                f"{self._xrpc}/com.atproto.server.refreshSession",
                headers={"Authorization": f"Bearer {self._session['refreshJwt']}"},
            )
            if response.is_success:
                self._session = response.json()
            else:
                await self._login()

    async def _create_record(self, record: dict) -> httpx.Response:
        return await self.client.post(
            f"{self._xrpc}/com.atproto.repo.createRecord",
            headers={"Authorization": f"Bearer {self._session['accessJwt']}"},
            json={"repo": self._session["did"], "collection": "app.bsky.feed.post", "record": record},
        )

    async def publish(self, message: str, link: str) -> PublishedPost:
        async with self._lock:
            if self._session is None:
                await self._login()

        created_at = datetime.now(timezone.utc)
        record = {
            "$type": "app.bsky.feed.post",
            "text": message,
            "createdAt": created_at.isoformat().replace("+00:00", "Z"),
            "facets": [link_facet(message, link)],
        }
        access = self._session["accessJwt"]
        response = await self._create_record(record)
        if _is_expired(response):
            # Safe to resend: the server rejected the first call, so nothing was published.
            await self._refresh(access)
            response = await self._create_record(record)
        ensure_ok(response)

        uri = response.json()["uri"]
        handle = self._session.get("handle") or self._value("BLUESKY_HANDLE")
        return PublishedPost(
            url=f"https://bsky.app/profile/{handle}/post/{uri.rsplit('/', 1)[-1]}",
            created_at=created_at,
            raw_id=uri,
        )

    async def check_public(self, post: PublishedPost) -> bool:
        # bsky.app returns 200 for any path, so ask the public AppView for the post itself.
        response = await self.client.get(
            f"{PUBLIC_APPVIEW}/app.bsky.feed.getPostThread",
            params={"uri": post.raw_id},
            timeout=self.settings.public_check_timeout_seconds,
        )
        if response.status_code != 200:
            return False
        return response.json().get("thread", {}).get("post", {}).get("uri") == post.raw_id
