"""Engine and session construction.

The engine is built once per process and the session factory hangs off it. The
context manager is the only supported way to get a session, because it is the
only thing that guarantees the rollback on the way out.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backpacking.config import Settings, get_settings
from backpacking.errors import ConfigurationError
from backpacking.storage.schema import Base


def build_engine(settings: Settings | None = None, *, echo: bool = False) -> Engine:
    """Create an engine from settings, with SQLite taught to keep its promises."""
    resolved = settings or get_settings()
    url = resolved.database_url
    if not url:
        raise ConfigurationError("database_url is empty")
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(url, echo=echo, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        _enable_sqlite_foreign_keys(engine)
    return engine


def _enable_sqlite_foreign_keys(engine: Engine) -> None:
    """SQLite ignores foreign keys unless told not to, once per connection.

    Without this the cascade deletes in the schema silently do nothing, and a
    corridor deleted in a test leaves its waypoints behind to fail the next one.
    """

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def create_all(engine: Engine) -> None:
    """Create every table. Migrations own this in deployment; tests use it."""
    Base.metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    Base.metadata.drop_all(engine)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """A transactional scope. Commits on success, rolls back on anything else."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class Database:
    """Engine, factory and lifecycle in one object, for the API and the CLI."""

    __slots__ = ("engine", "factory", "settings")

    def __init__(self, settings: Settings | None = None, *, echo: bool = False) -> None:
        self.settings = settings or get_settings()
        self.engine = build_engine(self.settings, echo=echo)
        self.factory = build_session_factory(self.engine)

    def create_all(self) -> None:
        create_all(self.engine)

    def drop_all(self) -> None:
        drop_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with session_scope(self.factory) as session:
            yield session

    def dispose(self) -> None:
        self.engine.dispose()

    def __repr__(self) -> str:
        return f"Database({self.engine.url.render_as_string(hide_password=True)!r})"
