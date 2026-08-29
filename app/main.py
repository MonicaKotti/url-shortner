from __future__ import annotations

import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.cache import LinkCache
from app.config import Settings
from app.database import Database
from app.errors import LinkConflict, LinkError, LinkGone, LinkNotFound
from app.metrics import ApplicationMetrics
from app.rate_limit import SlidingWindowRateLimiter
from app.repository import LinkRepository
from app.schemas import AnalyticsResponse, CreateLinkRequest, LinkResponse
from app.service import LinkService


def create_app(settings: Settings | None = None) -> FastAPI:
    configuration = settings or Settings.from_env()
    configuration.validate()
    database = Database(configuration.database_path)
    repository = LinkRepository(database)
    cache = LinkCache(configuration.cache_ttl_seconds)
    service = LinkService(repository, cache, configuration.public_base_url, configuration.analytics_salt)
    limiter = SlidingWindowRateLimiter(configuration.rate_limit_per_minute)
    metrics = ApplicationMetrics()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        yield

    application = FastAPI(
        title="Agentic URL Shortener",
        version="1.0.0",
        description="Deterministic URL-shortener data plane. Agentic SDLC tooling remains outside the request path.",
        lifespan=lifespan,
    )
    application.state.database = database
    application.state.link_service = service
    static_directory = Path(__file__).with_name("static")

    @application.middleware("http")
    async def operational_headers(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))[:128]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = (
            "no-store" if request.url.path.startswith("/api/") else response.headers.get("Cache-Control", "no-store")
        )
        if request.url.path == "/" or request.url.path.startswith("/_assets"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
                "form-action 'self'; frame-ancestors 'none'"
            )
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
            response.headers["X-Frame-Options"] = "DENY"
        return response

    def client_ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def rate_limit(request: Request, scope: str) -> None:
        if not limiter.allow(f"{scope}:{client_ip(request)}"):
            metrics.increment("rate_limited")
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

    def require_admin(x_admin_key: str | None = Header(default=None)) -> None:
        if x_admin_key is None or not secrets.compare_digest(x_admin_key, configuration.admin_api_key):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Valid X-Admin-Key required")

    @application.exception_handler(LinkNotFound)
    async def not_found_handler(_: Request, error: LinkNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @application.exception_handler(LinkGone)
    async def gone_handler(_: Request, error: LinkGone) -> JSONResponse:
        metrics.increment("redirect_errors")
        return JSONResponse(status_code=410, content={"detail": str(error)})

    @application.exception_handler(LinkConflict)
    async def conflict_handler(_: Request, error: LinkConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @application.exception_handler(LinkError)
    async def bad_request_handler(_: Request, error: LinkError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @application.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/ready", tags=["operations"])
    def ready() -> JSONResponse:
        available = database.ready()
        return JSONResponse(
            status_code=200 if available else 503, content={"status": "ready" if available else "unavailable"}
        )

    @application.get("/metrics", response_class=PlainTextResponse, tags=["operations"])
    def prometheus_metrics() -> str:
        return metrics.render()

    @application.get("/", include_in_schema=False, response_class=FileResponse)
    def web_interface() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    application.mount("/_assets", StaticFiles(directory=static_directory), name="static-assets")

    @application.post("/api/v1/links", response_model=LinkResponse, status_code=201, tags=["links"])
    def create_link(
        payload: CreateLinkRequest,
        request: Request,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        rate_limit(request, "create")
        created = service.create(str(payload.url), payload.custom_alias, payload.expires_at, idempotency_key)
        metrics.increment("links_created")
        response.headers["Location"] = created["short_url"]
        return created

    @application.get(
        "/api/v1/links", response_model=list[LinkResponse], tags=["links"], dependencies=[Depends(require_admin)]
    )
    def list_links(limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0)) -> list[dict]:
        return service.list(limit, offset)

    @application.get(
        "/api/v1/links/{code}", response_model=LinkResponse, tags=["links"], dependencies=[Depends(require_admin)]
    )
    def get_link(code: str) -> dict:
        return service.get(code)

    @application.get(
        "/api/v1/links/{code}/analytics",
        response_model=AnalyticsResponse,
        tags=["analytics"],
        dependencies=[Depends(require_admin)],
    )
    def get_analytics(code: str) -> dict:
        return service.analytics(code)

    @application.delete("/api/v1/links/{code}", status_code=204, tags=["links"], dependencies=[Depends(require_admin)])
    def disable_link(code: str) -> Response:
        service.disable(code)
        return Response(status_code=204)

    @application.get("/{code}", include_in_schema=False)
    def redirect(code: str, request: Request) -> RedirectResponse:
        rate_limit(request, "redirect")
        with metrics.redirect_timer():
            target = service.resolve(
                code,
                request.headers.get("referer", ""),
                request.headers.get("user-agent", ""),
                client_ip(request),
            )
        metrics.increment("redirects")
        return RedirectResponse(target, status_code=307)

    return application


app = create_app()
