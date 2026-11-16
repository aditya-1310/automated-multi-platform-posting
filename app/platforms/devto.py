"""DEV.to (Forem) API: publish an article.

Docs: https://developers.forem.com/api/v1#tag/articles/operation/createArticle
"""

from app.platforms.base import Platform, PublishedPost, ensure_ok, parse_timestamp, title_from


class DevToPlatform(Platform):
    name = "DEV.to"
    required_settings = ("DEVTO_API_KEY",)

    async def publish(self, message: str, link: str) -> PublishedPost:
        response = await self.client.post(
            "https://dev.to/api/articles",
            headers={"api-key": self._value("DEVTO_API_KEY"), "Accept": "application/vnd.forem.api-v1+json"},
            json={"article": {"title": title_from(message, link), "body_markdown": message, "published": True}},
        )
        ensure_ok(response)
        data = response.json()
        return PublishedPost(
            url=data["url"], created_at=parse_timestamp(data.get("published_at") or data.get("created_at"))
        )
