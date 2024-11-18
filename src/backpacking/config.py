"""Process wide settings.

Everything is read once from the environment. Nothing else in the package calls
``os.environ`` directly, so a test can build a ``Settings`` instance by hand and
pass it in rather than mutating global state.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backpacking.errors import ConfigurationError


class Settings(BaseSettings):
    """Runtime configuration, all of it overridable through the environment."""

    model_config = SettingsConfigDict(
        env_prefix="BACKPACKING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Where corridor datasheets and GPX exports are kept on disk.
    data_dir: Path = Field(default=Path("data"))

    # Database URL used by the storage package. SQLite is fine for a single
    # planner working offline; the deployed service points this at Postgres.
    database_url: str = Field(default="sqlite+pysqlite:///./backpacking.sqlite3")

    # Solver budget. The day splitter is a dynamic program over candidate camps,
    # and these two numbers bound how wide it is allowed to get.
    solver_max_candidates_per_day: int = Field(default=40, ge=1, le=500)
    solver_max_days: int = Field(default=200, ge=1, le=400)

    # Default planning assumptions. A request may override any of them.
    default_target_daily_miles: float = Field(default=18.0, gt=0.0, le=60.0)
    default_max_daily_gain_ft: int = Field(default=6000, gt=0)
    default_water_capacity_liters: float = Field(default=4.0, gt=0.0, le=12.0)

    # Logging.
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return upper

    def data_path(self, *parts: str) -> Path:
        """Resolve a path under :attr:`data_dir` without escaping it."""
        candidate = self.data_dir.joinpath(*parts).resolve()
        root = self.data_dir.resolve()
        if root != candidate and root not in candidate.parents:
            raise ConfigurationError(
                "resolved path escapes the configured data directory",
                data_dir=str(root),
                candidate=str(candidate),
            )
        return candidate


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process wide settings, built once and cached."""
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings. Only tests should need this."""
    get_settings.cache_clear()
