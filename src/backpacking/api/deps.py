"""Dependency wiring.

The database handle lives on the application state rather than in a module
global, so a test can build an app against a temporary file and two apps can
coexist in one process. Everything a route needs arrives through a dependency,
which is also what makes the routes trivial to test in isolation.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from backpacking.config import Settings
from backpacking.errors import ConfigurationError
from backpacking.services.planning import PlanningService
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    PlanRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.storage.session import Database


def get_database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise ConfigurationError("the application has no database attached")
    return database  # type: ignore[no-any-return]


def get_settings_dep(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise ConfigurationError("the application has no settings attached")
    return settings  # type: ignore[no-any-return]


def get_session(database: Database = Depends(get_database)) -> Iterator[Session]:
    """One transactional session per request."""
    with database.session() as session:
        yield session


def get_corridors(session: Session = Depends(get_session)) -> CorridorRepository:
    return CorridorRepository(session)


def get_water(session: Session = Depends(get_session)) -> WaterRepository:
    return WaterRepository(session)


def get_permits(session: Session = Depends(get_session)) -> PermitRepository:
    return PermitRepository(session)


def get_resupply(session: Session = Depends(get_session)) -> ResupplyRepository:
    return ResupplyRepository(session)


def get_plans(session: Session = Depends(get_session)) -> PlanRepository:
    return PlanRepository(session)


def get_service(session: Session = Depends(get_session)) -> PlanningService:
    """The planning use cases, over this request's session."""
    return PlanningService(session)
