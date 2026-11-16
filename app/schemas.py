"""Request/response models and the message validation rules."""

import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, TypeAdapter, ValidationError, field_validator

MAX_MESSAGE_LENGTH = 200

# Counts http(s) links and bare www. links, so a second link cannot slip in without a scheme.
LINK_PATTERN = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"]+")
TRAILING_PUNCTUATION = ".,;:!?)'\""

_http_url = TypeAdapter(AnyHttpUrl)


def extract_links(text: str) -> list[str]:
    return [match.group(0).rstrip(TRAILING_PUNCTUATION) for match in LINK_PATTERN.finditer(text)]


def validate_cta_link(link: str) -> None:
    """Raise ValueError if `link` is not a public http(s) URL."""
    if not link.lower().startswith(("http://", "https://")):
        raise ValueError("CTA link must start with http:// or https://")

    parts = urlsplit(link)
    if parts.username or parts.password:
        raise ValueError("CTA link must not contain credentials")

    host = (parts.hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("CTA link must be publicly reachable (localhost is not allowed)")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise ValueError("CTA link must be publicly reachable (private or loopback IP is not allowed)")
    if "." not in host:
        raise ValueError("CTA link must have a valid domain")

    try:
        _http_url.validate_python(link)
    except ValidationError:
        raise ValueError("CTA link is not a valid URL") from None


class PostingRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "message": "Check out our latest business platform and grow your online visibility. "
                    "https://example.com"
                }
            ]
        },
    )

    message: str

    @field_validator("message")
    @classmethod
    def check_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Message must not be empty")
        if len(value) > MAX_MESSAGE_LENGTH:
            raise ValueError(f"Message must be at most {MAX_MESSAGE_LENGTH} characters (got {len(value)})")
        links = extract_links(value)
        if len(links) != 1:
            raise ValueError(f"Message must contain exactly one CTA link (found {len(links)})")
        validate_cta_link(links[0])
        return value

    @property
    def link(self) -> str:
        """The CTA link exactly as typed (never Pydantic's normalized form)."""
        return extract_links(self.message)[0]


class PlatformResult(BaseModel):
    platform: str
    status: Literal["success", "failed"]
    posted_url: str | None = None
    public_access: bool = False
    date: str | None = None
    time: str | None = None
    error: str | None = None


class PostingResponse(BaseModel):
    success: bool
    results: list[PlatformResult]


class ErrorDetail(BaseModel):
    field: str | None
    message: str


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    errors: list[ErrorDetail]
