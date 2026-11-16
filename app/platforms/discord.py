"""Discord webhook: post into a server channel. Never public (members only).

Docs: https://discord.com/developers/docs/resources/webhook#execute-webhook
"""

from app.platforms.base import Platform, PublishedPost, ensure_ok, parse_timestamp


class DiscordPlatform(Platform):
    name = "Discord"
    required_settings = ("DISCORD_WEBHOOK_URL",)

    def __init__(self, settings, client) -> None:
        super().__init__(settings, client)
        self._guild_id: str | None = None

    def secrets(self) -> list[str]:
        url = self._value("DISCORD_WEBHOOK_URL")
        return [url, url.rstrip("/").rsplit("/", 1)[-1]] if url else []

    async def _get_guild_id(self, webhook: str) -> str:
        # The message object has no guild_id; the webhook object does. Fetched once, before posting,
        # so a failure here never leaves a post that we report as failed.
        if self._guild_id is None:
            response = await self.client.get(webhook)
            ensure_ok(response)
            self._guild_id = str(response.json()["guild_id"])
        return self._guild_id

    async def publish(self, message: str, link: str) -> PublishedPost:
        webhook = self._value("DISCORD_WEBHOOK_URL")
        guild_id = await self._get_guild_id(webhook)
        response = await self.client.post(
            webhook,
            params={"wait": "true"},
            json={"content": message, "allowed_mentions": {"parse": []}},  # never ping @everyone
        )
        ensure_ok(response)
        data = response.json()
        return PublishedPost(
            url=f"https://discord.com/channels/{guild_id}/{data['channel_id']}/{data['id']}",
            created_at=parse_timestamp(data.get("timestamp")),
        )

    async def check_public(self, post: PublishedPost) -> bool:
        return False
