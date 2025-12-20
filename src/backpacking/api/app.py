"""The application factory.

A factory rather than a module level ``app`` object, because a test needs to
build one against a temporary database and the deployment needs to build one
against the real settings, and a module global cannot be both.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from backpacking import __version__
from backpacking.api.errors import install_error_handlers
from backpacking.api.routes import corridors, health, permits, plans, resupply, water
from backpacking.config import Settings, get_settings
from backpacking.storage.session import Database

DESCRIPTION = """
Itinerary, permit and resupply logistics for long distance trail corridors.

Corridors are addressed by slug and everything on one is addressed by cumulative
mile from the southern or western terminus. Distances are statute miles,
elevations are feet, masses are pounds and volumes are litres, and every field
name says which.
""".strip()


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    create_tables: bool = False,
) -> FastAPI:
    """Build an application. Pass a database to share one with a test."""
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        handle = database or Database(resolved)
        if create_tables:
            handle.create_all()
        app.state.database = handle
        app.state.settings = resolved
        try:
            yield
        finally:
            if database is None:
                handle.dispose()

    app = FastAPI(
        title="backpacking",
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    install_error_handlers(app)
    install_timing_header(app)
    app.include_router(health.router)
    app.include_router(corridors.router)
    app.include_router(plans.router)
    app.include_router(permits.router)
    app.include_router(water.router)
    app.include_router(resupply.router)
    return app


def install_timing_header(app: FastAPI) -> None:
    """Report how long each request took, which is the first thing anyone asks."""

    @app.middleware("http")
    async def _timing(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"
        return response
