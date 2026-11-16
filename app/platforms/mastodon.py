"""Mastodon REST API: publish a public status.

Docs: https://docs.joinmastodon.org/methods/statuses/#create
"""

from app.platforms.base import Platform, PublishedPost, ensure_ok, parse_timestamp


class MastodonPlatform(Platform):
    name = "Mastodon"
    required_settings = ("MASTODON_BASE_URL", "MASTODON_ACCESS_TOKEN")

    async def publish(self, message: str, link: str) -> PublishedPost:
        base = self._value("MASTODON_BASE_URL").rstrip("/")
        response = await self.client.post(
            f"{base}/api/v1/statuses",
            headers={"Authorization": f"Bearer {self._value('MASTODON_ACCESS_TOKEN')}"},
            json={"status": message, "visibility": "public"},
        )
        ensure_ok(response)
        data = response.json()
        return PublishedPost(url=data["url"], created_at=parse_timestamp(data.get("created_at")))
