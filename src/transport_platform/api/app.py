from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from transport_platform.api.repository import AnalyticsRepository
from transport_platform.settings import get_settings

PACKAGE_DIRECTORY = Path(__file__).resolve().parents[1]
DASHBOARD_DIRECTORY = PACKAGE_DIRECTORY / "dashboard"
STATIC_DIRECTORY = DASHBOARD_DIRECTORY / "static"
TEMPLATE_DIRECTORY = DASHBOARD_DIRECTORY / "templates"


def _repository(request: Request) -> AnalyticsRepository:
    return request.app.state.analytics_repository


def _unavailable(detail: str) -> HTTPException:
    return HTTPException(status_code=503, detail=detail)


def create_app(database_path: Path | None = None) -> FastAPI:
    """Create the public transport intelligence application."""

    resolved_path = database_path or get_settings().serving_sqlite_path
    application = FastAPI(
        title="Greater Manchester Transport Intelligence",
        description=(
            "Governed scheduled public transport intelligence for "
            "Greater Manchester."
        ),
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    application.state.analytics_repository = AnalyticsRepository(resolved_path)
    application.add_middleware(GZipMiddleware, minimum_size=1_000)
    application.mount(
        "/static",
        StaticFiles(directory=STATIC_DIRECTORY),
        name="static",
    )
    templates = Jinja2Templates(directory=TEMPLATE_DIRECTORY)

    @application.middleware("http")
    async def response_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "public, max-age=60"
        return response

    @application.get("/health")
    def health(request: Request, response: Response) -> dict[str, Any]:
        try:
            health_payload = _repository(request).health()
        except Exception:
            response.status_code = 503
            return {
                "status": "unavailable",
                "service": "greater-manchester-transport-intelligence",
                "detail": "Serving analytics database is unavailable",
            }
        return {
            "service": "greater-manchester-transport-intelligence",
            **health_payload,
        }

    @application.get("/api/overview")
    def overview(request: Request) -> dict[str, Any]:
        try:
            return _repository(request).overview()
        except Exception as error:
            raise _unavailable("Unable to load executive overview") from error

    @application.get("/api/network-trends")
    def network_trends(
        request: Request,
        days: int = Query(90, ge=7, le=366),
        mode: str | None = Query(None, max_length=40),
    ) -> list[dict[str, Any]]:
        try:
            return _repository(request).network_trends(days=days, mode=mode)
        except Exception as error:
            raise _unavailable("Unable to load network trends") from error

    @application.get("/api/modes")
    def modes(request: Request) -> list[dict[str, Any]]:
        try:
            return _repository(request).modes()
        except Exception as error:
            raise _unavailable("Unable to load transport modes") from error

    @application.get("/api/routes")
    def routes(
        request: Request,
        limit: int = Query(12, ge=1, le=100),
        mode: str | None = Query(None, max_length=40),
        sort_by: str = Query("service", pattern="^(service|trips|frequency|coverage)$"),
    ) -> list[dict[str, Any]]:
        try:
            return _repository(request).routes(
                limit=limit,
                mode=mode,
                sort_by=sort_by,
            )
        except Exception as error:
            raise _unavailable("Unable to load route intelligence") from error

    @application.get("/api/stops")
    def stops(
        request: Request,
        limit: int = Query(12, ge=1, le=250),
        search: str | None = Query(None, max_length=120),
    ) -> list[dict[str, Any]]:
        try:
            return _repository(request).stops(limit=limit, search=search)
        except Exception as error:
            raise _unavailable("Unable to load stop intelligence") from error

    @application.get("/api/map-stops")
    def map_stops(
        request: Request,
        limit: int = Query(1_500, ge=100, le=5_000),
    ) -> list[dict[str, Any]]:
        try:
            return _repository(request).map_stops(limit=limit)
        except Exception as error:
            raise _unavailable("Unable to load the stop map") from error

    @application.get("/api/operators")
    def operators(
        request: Request,
        limit: int = Query(12, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        try:
            return _repository(request).operators(limit=limit)
        except Exception as error:
            raise _unavailable("Unable to load operator intelligence") from error

    @application.get("/api/locations")
    def locations(request: Request) -> list[dict[str, Any]]:
        try:
            return _repository(request).locations()
        except Exception as error:
            raise _unavailable("Unable to load location intelligence") from error

    @application.get("/api/publication-changes")
    def publication_changes(
        request: Request,
        limit: int = Query(50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            return _repository(request).publication_changes(limit=limit)
        except Exception as error:
            raise _unavailable("Unable to load publication changes") from error

    @application.get("/api/pipelines")
    def pipelines(request: Request) -> dict[str, Any]:
        try:
            return _repository(request).pipelines()
        except Exception as error:
            raise _unavailable("Unable to load pipeline health") from error

    @application.get("/api/data-quality")
    def data_quality(
        request: Request,
        limit: int = Query(100, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            return _repository(request).data_quality(limit=limit)
        except Exception as error:
            raise _unavailable("Unable to load data quality results") from error

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @application.get("/", response_class=HTMLResponse, include_in_schema=False)
    def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "title": "Greater Manchester Transport Intelligence",
            },
        )

    return application


app = create_app(
    Path(
        os.getenv(
            "SERVING_SQLITE_PATH",
            "data/serving/transport_dashboard.db",
        )
    )
)
