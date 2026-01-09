"""Shared state for the command line.

Typer callbacks put one of these on the context object, so every command reaches
the database the same way and a global flag such as ``--database`` is handled in
exactly one place.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backpacking.config import Settings
from backpacking.storage.repository import (
    CorridorRepository,
    PermitRepository,
    PlanRepository,
    ResupplyRepository,
    WaterRepository,
)
from backpacking.storage.session import Database


@dataclass(slots=True)
class CliContext:
    """Settings and a lazily built database handle."""

    settings: Settings
    quiet: bool = False
    _database: Database | None = field(default=None, repr=False)

    @property
    def database(self) -> Database:
        if self._database is None:
            self._database = Database(self.settings)
        return self._database

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.database.session() as session:
            yield session

    @contextmanager
    def corridors(self) -> Iterator[CorridorRepository]:
        with self.session() as session:
            yield CorridorRepository(session)

    @contextmanager
    def repositories(self) -> Iterator[tuple[Session, CorridorRepository]]:
        with self.session() as session:
            yield session, CorridorRepository(session)

    def water(self, session: Session) -> WaterRepository:
        return WaterRepository(session)

    def permits(self, session: Session) -> PermitRepository:
        return PermitRepository(session)

    def resupply(self, session: Session) -> ResupplyRepository:
        return ResupplyRepository(session)

    def plans(self, session: Session) -> PlanRepository:
        return PlanRepository(session)

    def close(self) -> None:
        if self._database is not None:
            self._database.dispose()
            self._database = None


def build_context(database_url: str | None = None, *, quiet: bool = False) -> CliContext:
    """Build a context, overriding the database URL if one was passed."""
    settings = Settings(database_url=database_url) if database_url else Settings()
    return CliContext(settings=settings, quiet=quiet)
