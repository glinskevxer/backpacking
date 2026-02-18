"""Request scoped middleware.

The timing header started life inline in the application factory. It has grown
a request id, a structured access log and a metrics hook, and all four want the
same start time and the same request object, so they belong in one place rather
than four decorators fighting over the ordering.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

from backpacking.observability.logging import bind_request, clear_request, get_logger
from backpacking.observability.metrics import REGISTRY

REQUEST_ID_HEADER = "x-request-id"
RESPONSE_TIME_HEADER = "x-response-time-ms"

logger = get_logger("backpacking.api.access")


def install_request_middleware(app: FastAPI) -> None:
    """Attach request id, timing, access logging and metrics in one pass."""

    @app.middleware("http")
    async def _request_scope(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        bind_request(request_id, path=request.url.path, method=request.method)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return _finish(response, request_id, started)
        finally:
            elapsed = time.perf_counter() - started
            REGISTRY.observe("http_request_seconds", elapsed)
            REGISTRY.increment("http_requests_total")
            REGISTRY.increment(f"http_responses_{status // 100}xx")
            logger.info(
                "request finished",
                status=status,
                duration_ms=round(elapsed * 1000.0, 2),
            )
            clear_request()


def _finish(response: Response, request_id: str, started: float) -> Response:
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    response.headers[RESPONSE_TIME_HEADER] = f"{elapsed_ms:.1f}"
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def install_metrics_endpoint(app: FastAPI, path: str = "/metrics") -> None:
    """Expose the registry. Not Prometheus format, and not pretending to be."""

    @app.get(path, tags=["health"], include_in_schema=False)
    def metrics() -> dict[str, object]:
        return REGISTRY.snapshot()
