"""GitHub Gists API: create a public gist.

Docs: https://docs.github.com/en/rest/gists/gists#create-a-gist
"""

from app.platforms.base import Platform, PublishedPost, ensure_ok, parse_timestamp, title_from


class GitHubGistPlatform(Platform):
    name = "GitHub Gist"
    required_settings = ("GITHUB_TOKEN",)

    async def publish(self, message: str, link: str) -> PublishedPost:
        response = await self.client.post(
            "https://api.github.com/gists",
            headers={
                "Authorization": f"Bearer {self._value('GITHUB_TOKEN')}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={
                "description": title_from(message, link),
                "public": True,
                "files": {"post.md": {"content": message}},
            },
        )
        ensure_ok(response)
        data = response.json()
        return PublishedPost(url=data["html_url"], created_at=parse_timestamp(data.get("created_at")))
