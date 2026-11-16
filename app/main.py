"""FastAPI app: one endpoint, POST /posting, that publishes a message to every configured platform."""

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from app.config import Settings, get_settings
from app.platforms import build_platforms
from app.schemas import ErrorDetail, ErrorResponse, PostingRequest, PostingResponse
from app.services.posting_service import PostingService

logger = logging.getLogger("posting")


def configure_logging(log_file: str) -> None:
    if logger.handlers:
        return
    formatter = logging.Formatter("%(asctime)sZ %(levelname)s %(name)s %(message)s", "%Y-%m-%dT%H:%M:%S")
    formatter.converter = time.gmtime  # log timestamps in UTC, like the API
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    except OSError:
        pass  # read-only serverless filesystem (e.g. Vercel): log to stdout only
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _init_service(app: FastAPI, client: httpx.AsyncClient) -> PostingService:
    settings: Settings = get_settings()
    configure_logging(settings.log_file)
    platforms = build_platforms(settings, client)  # built once so Bluesky/Discord caches persist
    service = PostingService(platforms, settings.platform_timeout_seconds, settings.public_check_timeout_seconds)
    app.state.posting_service = service
    configured = [p.name for p in platforms if not p.missing_settings()]
    logger.info("Configured platforms: %s", ", ".join(configured) or "none")
    return service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One shared client for all platforms. Auth is passed per request, never as a client default,
    # because the same client makes anonymous public-access checks.
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
        _init_service(app, client)
        yield


def get_posting_service(request: Request) -> PostingService:
    service = getattr(request.app.state, "posting_service", None)
    if service is None:
        # Fallback for serverless ASGI hosts that do not run lifespan hooks
        client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        service = _init_service(request.app, client)
    return service


def _error_field(loc: tuple) -> str | None:
    parts = [str(p) for p in loc if p != "body" and not isinstance(p, int)]
    return ".".join(parts) or None


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = []
    for err in exc.errors():
        if err.get("type") == "value_error" and "error" in err.get("ctx", {}):
            message = str(err["ctx"]["error"])  # our own rule message, without "Value error, "
        else:
            message = err["msg"]
        errors.append(ErrorDetail(field=_error_field(tuple(err.get("loc", ()))), message=message))
    return JSONResponse(status_code=422, content=ErrorResponse(errors=errors).model_dump())


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    body = ErrorResponse(errors=[ErrorDetail(field=None, message="Internal server error")])
    return JSONResponse(status_code=500, content=body.model_dump())


def create_app() -> FastAPI:
    app = FastAPI(
        title="Automated Multi-Platform Posting API",
        version="1.0.0",
        description="Publishes one short message with a single CTA link to several third-party platforms.",
        lifespan=lifespan,
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @app.post(
        "/posting",
        response_model=PostingResponse,
        responses={422: {"model": ErrorResponse, "description": "Invalid message"}},
        summary="Publish a message to every configured platform",
    )
    async def posting(
        payload: PostingRequest,
        service: Annotated[PostingService, Depends(get_posting_service)],
    ) -> PostingResponse:
        return await service.post_all(payload.message, payload.link)

    return app


app = create_app()
