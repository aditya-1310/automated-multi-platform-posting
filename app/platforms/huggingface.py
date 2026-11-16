"""Hugging Face Hub API: open a discussion on our own public repo (the AI/LLM platform target).

Docs: https://huggingface.co/docs/huggingface_hub/guides/community
"""

from datetime import datetime, timezone

from app.platforms.base import Platform, PublishedPost, ensure_ok, title_from


class HuggingFacePlatform(Platform):
    name = "Hugging Face"
    required_settings = ("HF_TOKEN", "HF_REPO_ID")

    async def publish(self, message: str, link: str) -> PublishedPost:
        repo_type = self.settings.hf_repo_type
        repo_id = self._value("HF_REPO_ID")
        response = await self.client.post(
            f"https://huggingface.co/api/{repo_type}s/{repo_id}/discussions",
            headers={"Authorization": f"Bearer {self._value('HF_TOKEN')}"},
            json={"title": title_from(message, link), "description": message},
        )
        ensure_ok(response)
        number = response.json()["num"]
        prefix = "" if repo_type == "model" else f"{repo_type}s/"
        return PublishedPost(
            url=f"https://huggingface.co/{prefix}{repo_id}/discussions/{number}",
            created_at=datetime.now(timezone.utc),  # the create response carries no timestamp
        )
