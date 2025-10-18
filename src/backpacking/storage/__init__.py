"""Persistence. Nothing outside this package knows a database exists."""

from backpacking.storage.schema import Base

__all__ = ["Base"]
