# Automated Multi-Platform Posting System

A FastAPI service that validates a short marketing message containing a single call-to-action (CTA) link and publishes it concurrently across seven third-party platforms through their official REST APIs.

Built for the **Dxora Technologies / Chivox AI Python Practical Test**.

---

## 1. Architecture Overview

```text
Client / Swagger UI (/docs)
   │
   ▼  POST /posting  {"message": "..."}
FastAPI Route (app/main.py)
   │
   ▼
Pydantic Validation (app/schemas.py)
   ├── > 200 code points, != 1 link, non-http(s), or private/localhost host ──► HTTP 422 ErrorResponse
   │
   ▼  valid message + original CTA link
PostingService (app/services/posting_service.py)
   │  asyncio.gather(...) with per-platform timeout (15s) and failure isolation
   ├──► Telegram Bot API       (POST /bot<token>/sendMessage)
   ├──► Mastodon REST API      (POST /api/v1/statuses)
   ├──► GitHub Gists API       (POST /gists)
   ├──► Bluesky AT Protocol    (com.atproto.repo.createRecord + link facet)
   ├──► DEV.to Forem API       (POST /api/articles)
   ├──► Hugging Face Hub API   (POST /api/{type}s/{repo_id}/discussions)
   └──► Discord Webhook API    (POST /api/webhooks/{id}/{token}?wait=true)
   │
   ▼  anonymous public-access check per succeeded post (no auth headers sent)
HTTP 200 PostingResponse  {"success": true, "results": [...]}
```

---

## 2. Platform Research and Selection

Platforms were evaluated against four criteria:
1. Official documented REST API
2. Free self-service developer credentials (no manual vendor review queue)
3. Supports short text posts (up to 200 characters) with a clickable URL
4. Returns a deterministic URL for the published post

### Implemented Platforms (6 Public + 1 Community Bonus)

| # | Platform | Category | Official Endpoint | Auth Env Vars | Public Access Verification |
| :- | :--- | :--- | :--- | :--- | :--- |
| 1 | **Telegram** | Messaging / Social | `POST https://api.telegram.org/bot<token>/sendMessage` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL` | Anonymous `GET https://t.me/<channel>/<id>?embed=1&mode=tme` checking that the posted message text appears in the embed HTML |
| 2 | **Mastodon** | Social (Fediverse) | `POST <base_url>/api/v1/statuses` | `MASTODON_BASE_URL`, `MASTODON_ACCESS_TOKEN` | Anonymous `GET` of the returned status `url` (`HTTP 200`) |
| 3 | **GitHub Gist** | Developer Portal | `POST https://api.github.com/gists` | `GITHUB_TOKEN` | Anonymous `GET` of `html_url` (`HTTP 200`) |
| 4 | **Bluesky** | Social (AT Protocol) | `POST https://bsky.social/xrpc/com.atproto.repo.createRecord` | `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | Unauthenticated query to `https://public.api.bsky.app/xrpc/app.bsky.feed.getPostThread?uri=<at-uri>` |
| 5 | **DEV.to** | Developer Publishing | `POST https://dev.to/api/articles` | `DEVTO_API_KEY` | Anonymous `GET` of the published article `url` (`HTTP 200`) |
| 6 | **Hugging Face Hub** | AI / LLM Platform | `POST https://huggingface.co/api/{type}s/{repo_id}/discussions` | `HF_TOKEN`, `HF_REPO_ID`, `HF_REPO_TYPE` | Anonymous `GET` of the public repository discussion URL (`HTTP 200`) |
| 7 | **Discord** *(bonus)* | Community Chat | `POST <webhook_url>?wait=true` | `DISCORD_WEBHOOK_URL` | Always `false` (server channels require membership; included to demonstrate an honest `public_access: false` result) |

### Why Hugging Face Hub for "LLM Platforms"
Inference APIs (OpenAI, Anthropic, Google Gemini) generate model completions rather than hosting public user posts. Hugging Face Hub is the primary public registry for open-weight LLMs and datasets, and its official Hub REST API (`POST /api/{models|datasets|spaces}/{repo_id}/discussions`) publishes a permanent, publicly readable discussion thread on a target repository.

### Researched and Rejected Platforms

| Platform | Reason for Rejection |
| :--- | :--- |
| **X (Twitter)** | Retired its free posting tier for new developer accounts in favor of pay-per-use credits (posts containing links incur a per-request fee). Fails the free self-service criterion. |
| **Reddit** | Ended instant self-service OAuth app creation under the Responsible Builder Policy; new API applications require manual review, and automated cross-posting bots are routinely declined. |
| **LinkedIn** | Requires a registered Developer App linked to a verified Company Page plus 3-legged OAuth tokens that expire every 60 days. |
| **Meta (Instagram / Threads / Facebook)** | Requires Meta App Review and a linked Business or Creator account before publishing permissions are granted. |
| **Slack** | Incoming webhooks and `chat.postMessage` publish only inside private workspaces, never producing a publicly accessible URL. |

---

## 3. Project Structure

```text
automated-posting/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app factory, lifespan AsyncClient, 422/500 handlers, POST /posting
│   ├── config.py                # Settings loaded via pydantic-settings (SecretStr for credentials)
│   ├── schemas.py               # PostingRequest (+ validators), PlatformResult, PostingResponse, ErrorResponse
│   ├── platforms/
│   │   ├── __init__.py          # Fixed-order platform registry (build_platforms)
│   │   ├── base.py              # Platform ABC, PublishedPost, PlatformError, error mapping, secret redaction
│   │   ├── telegram.py          # Telegram Bot API adapter + embed text verification
│   │   ├── mastodon.py          # Mastodon statuses adapter
│   │   ├── github_gist.py       # GitHub Gists adapter
│   │   ├── bluesky.py           # Bluesky AT Protocol adapter (UTF-8 byte facets + cached session)
│   │   ├── devto.py             # DEV.to Forem articles adapter
│   │   ├── huggingface.py       # Hugging Face Hub discussions adapter
│   │   └── discord.py           # Discord webhook adapter (cached guild_id lookup)
│   └── services/
│       ├── __init__.py
│       └── posting_service.py   # Concurrent fan-out, per-platform timeouts, public check, UTC formatting
├── tests/
│   ├── conftest.py              # Shared fixtures and SSL context for fast offline tests
│   ├── test_validation.py       # 22 unit tests for message length and CTA URL validation
│   ├── test_posting_service.py  # 11 unit tests for fan-out, failure isolation, timeouts, and redaction
│   ├── test_platforms.py        # 31 respx-mocked adapter tests (payloads, facets, auth isolation)
│   └── test_posting_api.py      # 11 ASGI integration tests for 200, 422, 500, and /docs
├── docs/
│   └── screenshots/             # Captures of Swagger UI and live published posts
├── logs/
│   └── .gitkeep
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 4. Setup and Execution

### Prerequisites
- Python 3.11+

### 1. Clone and Install Dependencies

```bash
git clone https://github.com/aditya-1310/automated-multi-platform-posting.git
cd automated-multi-platform-posting

python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
cp .env.example .env
```

Fill in the credentials for the platforms you want to enable in `.env`. Any platform left blank is not called over the network; it is reported cleanly in the response as `"status": "failed"` with `"error": "Not configured: missing <ENV_VAR>"` while all configured platforms still publish.

| Platform | How to Obtain Credentials |
| :--- | :--- |
| **Telegram** | Message `@BotFather` with `/newbot` to get `TELEGRAM_BOT_TOKEN`. Create a public channel, add the bot as an administrator with `Post Messages` permission, and set `TELEGRAM_CHANNEL=@your_channel`. |
| **Mastodon** | On your instance (e.g. `https://mastodon.social`), go to `Preferences -> Development -> New application`, enable `write:statuses`, and copy your access token into `MASTODON_ACCESS_TOKEN`. |
| **GitHub Gist** | Create a Personal Access Token with `Gists: write` (fine-grained) or `gist` scope (classic) and set `GITHUB_TOKEN`. |
| **Bluesky** | Go to `Settings -> Privacy and security -> App passwords`, generate an app password, and set `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD`. |
| **DEV.to** | Go to `Settings -> Extensions -> DEV Community API Keys`, generate a key, and set `DEVTO_API_KEY`. |
| **Hugging Face** | Create a write token at `huggingface.co/settings/tokens` and a public dataset/model repo (with Discussions enabled), then set `HF_TOKEN`, `HF_REPO_ID`, and `HF_REPO_TYPE`. |
| **Discord** | In your server channel settings, open `Integrations -> Webhooks -> New Webhook` and copy the URL into `DISCORD_WEBHOOK_URL`. |

### 3. Start the Local Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000
```

Open interactive API documentation at:
- **Swagger UI:** `http://localhost:4000/docs`
- **OpenAPI JSON:** `http://localhost:4000/openapi.json`

### 4. Run the Offline Test Suite

All 75 tests run offline using `respx` to mock external HTTP calls:

```bash
pytest -q
```

---

## 5. API Reference and Sample Requests

### Endpoint

```http
POST http://localhost:4000/posting
Content-Type: application/json
```

### Input Validation Rules
1. `message` is required, must be a string, and cannot be empty after trimming whitespace.
2. `message` must be at most **200 Unicode code points** (`len(message) <= 200`).
3. `message` must contain **exactly one CTA link** (bare `www.` links are also counted so a second link cannot bypass detection).
4. The CTA link must start with `http://` or `https://`, contain a valid domain with a dot, carry no embedded credentials (`user:pass@`), and must not point to `localhost` or private/loopback IP addresses.
5. Unknown request body fields are rejected (`extra="forbid"`).
6. The link is sent to platforms **exactly as typed** in the message (Pydantic's normalized URL is used only for validation, avoiding unwanted trailing slashes).

### Sample Request (`curl`)

```bash
curl -X POST http://localhost:4000/posting \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Check out our latest business platform and grow your online visibility. https://example.com"
  }'
```

### Sample `200 OK` Response (Live Run Output)

```json
{
  "success": true,
  "results": [
    {
      "platform": "Telegram",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Not configured: missing TELEGRAM_BOT_TOKEN"
    },
    {
      "platform": "Mastodon",
      "status": "success",
      "posted_url": "https://mastodon.social/@aditya_bhadade_1310/117627643567864426",
      "public_access": true,
      "date": "2026-11-16",
      "time": "18:56:41",
      "error": null
    },
    {
      "platform": "GitHub Gist",
      "status": "success",
      "posted_url": "https://gist.github.com/aditya-1310/cc4510426459e41043771f4c29d196de",
      "public_access": true,
      "date": "2026-11-16",
      "time": "18:56:41",
      "error": null
    },
    {
      "platform": "Bluesky",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Not configured: missing BLUESKY_APP_PASSWORD"
    },
    {
      "platform": "DEV.to",
      "status": "success",
      "posted_url": "https://dev.to/aditya_bhadade_22c4126d28/publish-once-to-multiple-platforms-with-our-fastapi-servi-o1e",
      "public_access": true,
      "date": "2026-11-16",
      "time": "18:56:41",
      "error": null
    },
    {
      "platform": "Hugging Face",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Not configured: missing HF_TOKEN"
    },
    {
      "platform": "Discord",
      "status": "failed",
      "posted_url": null,
      "public_access": false,
      "date": null,
      "time": null,
      "error": "Not configured: missing DISCORD_WEBHOOK_URL"
    }
  ]
}
```

### Sample `422 Unprocessable Entity` Validation Error

Request:

```json
{
  "message": "Two links https://example.com and https://example.org"
}
```

Response (`HTTP 422`):

```json
{
  "success": false,
  "errors": [
    {
      "field": "message",
      "message": "Message must contain exactly one CTA link (found 2)"
    }
  ]
}
```

---

## 6. Execution Logs and Screenshots

### Sample Log Output (`logs/posting.log`)

All timestamps in responses and logs are recorded in **UTC**:

```text
2026-11-16T18:56:21Z INFO posting Configured platforms: Mastodon, GitHub Gist, DEV.to
2026-11-16T18:56:41Z INFO posting platform=Telegram status=failed duration_ms=0 url=None error=Not configured: missing TELEGRAM_BOT_TOKEN
2026-11-16T18:56:41Z INFO posting platform=Bluesky status=failed duration_ms=0 url=None error=Not configured: missing BLUESKY_APP_PASSWORD
2026-11-16T18:56:41Z INFO posting platform=Hugging Face status=failed duration_ms=0 url=None error=Not configured: missing HF_TOKEN
2026-11-16T18:56:41Z INFO posting platform=Discord status=failed duration_ms=0 url=None error=Not configured: missing DISCORD_WEBHOOK_URL
2026-11-16T18:56:42Z INFO posting platform=DEV.to status=success duration_ms=894 url=https://dev.to/aditya_bhadade_22c4126d28/publish-once-to-multiple-platforms-with-our-fastapi-servi-o1e error=None
2026-11-16T18:56:42Z INFO posting platform=Mastodon status=success duration_ms=1120 url=https://mastodon.social/@aditya_bhadade_1310/117627643567864426 error=None
2026-11-16T18:56:43Z INFO posting platform=GitHub Gist status=success duration_ms=1642 url=https://gist.github.com/aditya-1310/cc4510426459e41043771f4c29d196de error=None
```

### Screenshots

- **Swagger UI (`/docs`):** [`docs/screenshots/swagger_docs.png`](docs/screenshots/swagger_docs.png)
- **Live Published Mastodon Status:** [`docs/screenshots/mastodon_live.png`](docs/screenshots/mastodon_live.png)
- **Live Published GitHub Gist:** [`docs/screenshots/github_gist_live.png`](docs/screenshots/github_gist_live.png)
- **Live Published DEV.to Article:** [`docs/screenshots/devto_live.png`](docs/screenshots/devto_live.png)

---

## 7. Key Design Decisions and Known Limitations

- **Concurrent Fan-Out (`asyncio.gather`):** Publishing is I/O-bound. Each platform coroutine runs concurrently inside its own `asyncio.wait_for` timeout (`15s` default) and `try/except` block, so `_post_one` always returns a `PlatformResult` and one failing or hanging site never blocks the others.
- **No Retries on Publish (Idempotency):** Publishing a social post is not idempotent. If a network timeout occurs after the remote server accepts the request, retrying would create duplicate public posts. (Mastodon supports an `Idempotency-Key` header and could be retried safely in a future revision.)
- **Lost-Response Timeouts:** When `asyncio.wait_for` cancels a call at 15 seconds, the remote platform may still complete the post even though the result reports `"Timed out after 15s"`.
- **Per-Request Authentication Only:** The application shares a single `httpx.AsyncClient` created in FastAPI's `lifespan`. Credentials are passed strictly per request (`headers=`), never as client-level defaults, ensuring the anonymous `check_public` requests never leak an `Authorization` or `api-key` header to another domain.
- **Secret Redaction:** Telegram bot tokens and Discord webhook tokens appear inside request URLs, which `httpx` includes in exception text. Every error string is scrubbed against the adapter's `secrets()` list before logging or returning.
- **Bluesky UTF-8 Byte Offsets and Session Caching:** Bluesky requires explicit richtext `facets` with UTF-8 byte offsets (`byteStart`, `byteEnd`) to render links as clickable, and enforces strict rate limits on `createSession` (30 per 5 minutes, 300 per day). `BlueskyPlatform` computes UTF-8 byte slices and caches/refreshes its JWT session behind an `asyncio.Lock`.
- **Single UTC Clock Source:** Each succeeded post derives both `date` and `time` from a single UTC-normalized `datetime` object so a response never mixes timezones.
