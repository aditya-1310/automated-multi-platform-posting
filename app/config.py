"""Application settings, read from environment variables or a local .env file."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    platform_timeout_seconds: float = 15.0
    public_check_timeout_seconds: float = 5.0
    log_file: str = "logs/posting.log"

    telegram_bot_token: SecretStr | None = None
    telegram_channel: str | None = None  # public channel username, with or without "@"

    mastodon_base_url: str | None = None  # e.g. https://mastodon.social
    mastodon_access_token: SecretStr | None = None

    github_token: SecretStr | None = None  # fine-grained "Gists: write" or classic "gist" scope

    bluesky_handle: str | None = None  # e.g. yourname.bsky.social
    bluesky_app_password: SecretStr | None = None
    bluesky_service: str = "https://bsky.social"

    devto_api_key: SecretStr | None = None

    hf_token: SecretStr | None = None
    hf_repo_id: str | None = None  # e.g. yourname/automated-posting
    hf_repo_type: Literal["model", "dataset", "space"] = "dataset"

    discord_webhook_url: SecretStr | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
