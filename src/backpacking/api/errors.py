"""Turning domain errors into HTTP responses.

The mapping is explicit rather than clever. Every exception this package raises
deliberately has a status code chosen for it, and anything that arrives here
without one is a bug rather than a client error, so it becomes a 500 and gets
logged with its context intact.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backpacking.errors import (
    BackpackingError,
    ConfigurationError,
    CorridorError,
    DataSourceError,
    LoadoutError,
    PaceModelError,
    PermitError,
    PlanInfeasible,
    ResupplyInfeasible,
    ValidationFailed,
    WaterCarryError,
    WaypointNotFound,
)

logger = logging.getLogger("backpacking.api")

#: Every error class this API knows how to answer, and what it answers with.
STATUS_BY_ERROR: dict[type[BackpackingError], int] = {
    WaypointNotFound: 404,
    DataSourceError: 404,
    CorridorError: 422,
    PaceModelError: 422,
    WaterCarryError: 422,
    LoadoutError: 422,
    PermitError: 422,
    ValidationFailed: 422,
    ResupplyInfeasible: 409,
    PlanInfeasible: 409,
    ConfigurationError: 500,
}


def status_for(error: BackpackingError) -> int:
    """Most specific status registered for this error's class."""
    for candidate in type(error).__mro__:
        if candidate in STATUS_BY_ERROR:
            return STATUS_BY_ERROR[candidate]
    return 500


def install_error_handlers(app: FastAPI) -> None:
    """Attach the handlers to an application."""

    @app.exception_handler(BackpackingError)
    async def _handle_domain_error(_request: Request, error: BackpackingError) -> JSONResponse:
        status = status_for(error)
        if status >= 500:
            logger.exception("unhandled domain error", extra={"code": error.code})
        return JSONResponse(status_code=status, content=error.as_dict())

    @app.exception_handler(ValueError)
    async def _handle_value_error(_request: Request, error: ValueError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"code": "invalid_value", "message": str(error), "context": {}},
        )
