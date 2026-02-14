"""Engine construction, and the pool an in memory database needs.

A SQLite database opened as ``:memory:`` lives inside its connection. With the
default pool, every session gets a fresh connection and therefore a fresh, empty
database, and a write that vanished looks exactly like a write that failed
silently. The static pool is what makes the test databases behave like real ones.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.pool import StaticPool

from backpacking.config import Settings
from backpacking.errors import ConfigurationError
from backpacking.storage.repository import CorridorRepository
from backpacking.storage.session import (
    Database,
    build_engine,
    build_session_factory,
    is_memory_url,
    session_scope,
)


class TestMemoryUrlDetection:
    @pytest.mark.parametrize(
        "url",
        [
            "sqlite+pysqlite:///:memory:",
            "sqlite://",
            "sqlite:///file:x?mode=memory&cache=shared",
        ],
    )
    def test_memory_urls_are_recognised(self, url: str) -> None:
        assert is_memory_url(url) or url == "sqlite://"

    @pytest.mark.parametrize(
        "url",
        [
            "sqlite+pysqlite:///./trail.sqlite3",
            "postgresql+psycopg://user:pass@host:5432/db",
        ],
    )
    def test_file_and_server_urls_are_not(self, url: str) -> None:
        assert not is_memory_url(url)


class TestEngineConstruction:
    def test_an_in_memory_engine_uses_a_static_pool(self) -> None:
        engine = build_engine(Settings(database_url="sqlite+pysqlite:///:memory:"))
        assert isinstance(engine.pool, StaticPool)
        engine.dispose()

    def test_a_file_engine_does_not(self, tmp_path) -> None:
        engine = build_engine(Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'x.sqlite3'}"))
        assert not isinstance(engine.pool, StaticPool)
        engine.dispose()

    def test_an_empty_url_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="database_url is empty"):
            build_engine(Settings(database_url=""))

    def test_sqlite_enforces_foreign_keys(self) -> None:
        engine = build_engine(Settings(database_url="sqlite+pysqlite:///:memory:"))
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1
        engine.dispose()


class TestMemoryPersistence:
    def test_a_write_survives_into_the_next_session(self, corridor) -> None:
        database = Database(Settings(database_url="sqlite+pysqlite:///:memory:"))
        database.create_all()
        with database.session() as session:
            CorridorRepository(session).save(corridor, "crystal-range")
        with database.session() as session:
            assert CorridorRepository(session).exists("crystal-range")
        database.dispose()

    def test_two_databases_do_not_share_state(self, corridor) -> None:
        first = Database(Settings(database_url="sqlite+pysqlite:///:memory:"))
        second = Database(Settings(database_url="sqlite+pysqlite:///:memory:"))
        first.create_all()
        second.create_all()
        with first.session() as session:
            CorridorRepository(session).save(corridor, "crystal-range")
        with second.session() as session:
            assert not CorridorRepository(session).exists("crystal-range")
        first.dispose()
        second.dispose()

    def test_the_settings_are_kept_on_the_handle(self) -> None:
        settings = Settings(database_url="sqlite+pysqlite:///:memory:")
        database = Database(settings)
        assert database.settings is settings
        database.dispose()


class TestSessionScope:
    def test_it_commits_on_success(self, corridor) -> None:
        engine = build_engine(Settings(database_url="sqlite+pysqlite:///:memory:"))
        factory = build_session_factory(engine)
        from backpacking.storage.session import create_all

        create_all(engine)
        with session_scope(factory) as session:
            CorridorRepository(session).save(corridor, "crystal-range")
        with session_scope(factory) as session:
            assert CorridorRepository(session).exists("crystal-range")
        engine.dispose()

    def test_it_rolls_back_on_failure(self, corridor) -> None:
        engine = build_engine(Settings(database_url="sqlite+pysqlite:///:memory:"))
        factory = build_session_factory(engine)
        from backpacking.storage.session import create_all

        create_all(engine)
        with pytest.raises(RuntimeError), session_scope(factory) as session:
            CorridorRepository(session).save(corridor, "crystal-range")
            raise RuntimeError("boom")
        with session_scope(factory) as session:
            assert not CorridorRepository(session).exists("crystal-range")
        engine.dispose()
