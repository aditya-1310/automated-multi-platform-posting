"""End-to-end tests of the HTTP layer with the service swapped for a fake."""

import httpx
import pytest

from app.main import create_app, get_posting_service
from app.schemas import PlatformResult, PostingResponse

VALID = {"message": "Check out our latest business platform and grow your online visibility. https://example.com"}


class FakeService:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def post_all(self, message, link):
        self.calls.append((message, link))
        if self.error:
            raise self.error
        return self.response


MIXED = PostingResponse(
    success=True,
    results=[
        PlatformResult(platform="Platform A", status="success", posted_url="https://example.com/post/123",
                       public_access=True, date="2026-11-15", time="10:30:00", error=None),
        PlatformResult(platform="Platform B", status="failed", error="Authentication failed"),
    ],
)


def make_client(service) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_posting_service] = lambda: service
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_success_response_matches_brief_shape():
    service = FakeService(MIXED)
    async with make_client(service) as client:
        response = await client.post("/posting", json=VALID)

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "results": [
            {"platform": "Platform A", "status": "success", "posted_url": "https://example.com/post/123",
             "public_access": True, "date": "2026-11-15", "time": "10:30:00", "error": None},
            {"platform": "Platform B", "status": "failed", "posted_url": None, "public_access": False,
             "date": None, "time": None, "error": "Authentication failed"},
        ],
    }
    assert service.calls == [(VALID["message"], "https://example.com")]


async def test_all_failed_is_still_200_with_success_false():
    all_failed = PostingResponse(success=False, results=[PlatformResult(platform="A", status="failed", error="x")])
    async with make_client(FakeService(all_failed)) as client:
        response = await client.post("/posting", json=VALID)
    assert response.status_code == 200
    assert response.json()["success"] is False


@pytest.mark.parametrize(
    "payload,field,fragment",
    [
        ({"message": "no link here"}, "message", "exactly one CTA link (found 0)"),
        ({"message": "x" * 200 + " https://example.com"}, "message", "at most 200 characters"),
        ({}, "message", "Field required"),
        ({**VALID, "mesage": "typo"}, "mesage", "Extra inputs are not permitted"),
        ({"message": 123}, "message", "valid string"),
    ],
)
async def test_validation_errors_use_error_envelope(payload, field, fragment):
    service = FakeService(MIXED)
    async with make_client(service) as client:
        response = await client.post("/posting", json=payload)

    assert response.status_code == 422
    data = response.json()
    assert data["success"] is False
    assert data["errors"][0]["field"] == field
    assert fragment in data["errors"][0]["message"]
    assert not data["errors"][0]["message"].startswith("Value error")
    assert service.calls == []


async def test_malformed_json_is_422():
    async with make_client(FakeService(MIXED)) as client:
        response = await client.post("/posting", content=b"{not json", headers={"content-type": "application/json"})
    assert response.status_code == 422
    assert response.json()["success"] is False


async def test_unexpected_error_returns_500_envelope_without_details():
    async with make_client(FakeService(error=RuntimeError("secret internals"))) as client:
        response = await client.post("/posting", json=VALID)
    assert response.status_code == 500
    assert response.json() == {"success": False, "errors": [{"field": None, "message": "Internal server error"}]}


async def test_docs_and_openapi_load():
    async with make_client(FakeService(MIXED)) as client:
        docs = await client.get("/docs")
        schema = await client.get("/openapi.json")
    assert docs.status_code == 200
    assert "/posting" in schema.json()["paths"]
