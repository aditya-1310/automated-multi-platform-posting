import pytest
from pydantic import ValidationError

from app.schemas import PostingRequest

LINK = "https://example.com"


def make_message(total_len: int, link: str = LINK) -> str:
    """Build a message of exactly `total_len` code points that ends with ` <link>`."""
    filler = "a" * (total_len - len(link) - 1)
    return f"{filler} {link}"


def error_text(message) -> str:
    with pytest.raises(ValidationError) as exc:
        PostingRequest(message=message)
    return str(exc.value)


def test_exactly_200_characters_passes():
    req = PostingRequest(message=make_message(200))
    assert len(req.message) == 200
    assert req.link == LINK


def test_201_characters_fails():
    assert "at most 200 characters (got 201)" in error_text(make_message(201))


def test_surrounding_whitespace_is_stripped_before_counting():
    req = PostingRequest(message="   " + make_message(200) + "  \n")
    assert len(req.message) == 200


def test_blank_message_fails():
    assert "must not be empty" in error_text("   ")


def test_non_string_message_fails():
    with pytest.raises(ValidationError):
        PostingRequest(message=123)


def test_extra_field_fails():
    with pytest.raises(ValidationError) as exc:
        PostingRequest(message=make_message(50), mesage="typo")
    assert "Extra inputs are not permitted" in str(exc.value)


def test_no_link_fails():
    assert "exactly one CTA link (found 0)" in error_text("Grow your online visibility today")


def test_two_links_fail():
    text = "Visit https://example.com and https://example.org"
    assert "exactly one CTA link (found 2)" in error_text(text)


def test_www_and_https_count_as_two_links():
    text = "Visit www.example.com and https://example.org"
    assert "exactly one CTA link (found 2)" in error_text(text)


def test_scheme_less_www_link_is_rejected():
    assert "must start with http:// or https://" in error_text("Visit www.example.com now")


def test_ftp_link_is_not_a_cta_link():
    assert "exactly one CTA link (found 0)" in error_text("Get it at ftp://files.example.com")


@pytest.mark.parametrize(
    "url",
    ["https://localhost", "http://localhost:8000/x", "https://127.0.0.1", "https://192.168.1.5", "http://10.0.0.1/a"],
)
def test_local_and_private_hosts_are_rejected(url):
    assert "publicly reachable" in error_text(f"Try {url}")


def test_public_ip_literal_is_allowed():
    assert PostingRequest(message="Try https://8.8.8.8/page").link == "https://8.8.8.8/page"


def test_link_with_space_in_domain_is_rejected():
    assert "valid domain" in error_text("Visit https://exa mple.com")


def test_credentials_in_url_are_rejected():
    assert "must not contain credentials" in error_text("Visit https://user:pass@example.com")


def test_trailing_punctuation_is_trimmed():
    assert PostingRequest(message="Visit https://example.com.").link == LINK
    assert PostingRequest(message="(see https://example.com/a?b=1)!").link == "https://example.com/a?b=1"


def test_emoji_counts_in_code_points():
    # "👍🏽" is one visible character but two code points.
    emoji = "\U0001F44D\U0001F3FD"
    base = make_message(198)
    assert len(PostingRequest(message=emoji + base).message) == 200
    assert "got 201" in error_text(emoji + "x" + base)


def test_link_is_kept_exactly_as_typed():
    req = PostingRequest(message="Check out our platform https://Example.com")
    assert req.link == "https://Example.com"
    assert req.message.endswith("https://Example.com")
