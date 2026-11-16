"""Telegram Bot API: post to a public channel where the bot is an admin.

Docs: https://core.telegram.org/bots/api#sendmessage
"""

import html
import re

from app.platforms.base import Platform, PlatformError, PublishedPost, ensure_ok, parse_timestamp


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class TelegramPlatform(Platform):
    name = "Telegram"
    required_settings = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL")

    @property
    def channel(self) -> str:
        return self._value("TELEGRAM_CHANNEL").lstrip("@")

    async def publish(self, message: str, link: str) -> PublishedPost:
        token = self._value("TELEGRAM_BOT_TOKEN")
        # No parse_mode: user text is never interpreted as HTML or Markdown.
        response = await self.client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": f"@{self.channel}", "text": message},
        )
        ensure_ok(response)
        data = response.json()
        if not data.get("ok"):
            raise PlatformError(f"Platform error: {data.get('description', 'unknown')}")
        sent = data["result"]
        return PublishedPost(
            url=f"https://t.me/{self.channel}/{sent['message_id']}",
            created_at=parse_timestamp(sent.get("date")),
            text=message,
        )

    async def check_public(self, post: PublishedPost) -> bool:
        # t.me serves a page even for a missing message id, so confirm our text is in the embed.
        response = await self.client.get(
            post.url,
            params={"embed": "1", "mode": "tme"},
            follow_redirects=True,
            timeout=self.settings.public_check_timeout_seconds,
        )
        if response.status_code != 200:
            return False
        visible = _collapse(html.unescape(re.sub(r"<[^>]+>", " ", response.text)))
        return _collapse(post.text) in visible
