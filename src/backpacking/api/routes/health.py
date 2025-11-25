"""Liveness and readiness."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from backpacking import __version__
from backpacking.api.deps import get_session
from backpacking.api.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Liveness. Answers without touching anything that can be down."""
    return HealthOut(status="ok", version=__version__, database="not checked")


@router.get("/ready", response_model=HealthOut)
def ready(session: Session = Depends(get_session)) -> HealthOut:
    """Readiness. Actually round trips a query, because that is the point."""
    try:
        session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - readiness reports rather than raises
        return HealthOut(status="degraded", version=__version__, database="unreachable")
    return HealthOut(status="ok", version=__version__, database="reachable")
