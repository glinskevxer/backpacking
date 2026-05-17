"""The application factory.

A factory rather than a module level ``app`` object, because a test needs to
build one against a temporary database and the deployment needs to build one
against the real settings, and a module global cannot be both.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backpacking import __version__
from backpacking.api.errors import install_error_handlers
from backpacking.api.middleware import install_metrics_endpoint, install_request_middleware
from backpacking.api.routes import (
    corridors,
    health,
    permits,
    plans,
    reports,
    resupply,
    water,
)
from backpacking.config import Settings, get_settings
from backpacking.observability.logging import configure_logging
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
    configure_logging(resolved)

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
    install_request_middleware(app)
    install_metrics_endpoint(app)
    app.include_router(health.router)
    app.include_router(corridors.router)
    app.include_router(plans.router)
    app.include_router(permits.router)
    app.include_router(water.router)
    app.include_router(resupply.router)
    app.include_router(reports.router)
    return app
