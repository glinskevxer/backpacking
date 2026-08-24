"""What the service does about the open internet.

Three things, all off by default, because this started as a tool one person ran
on a laptop and most deployments still are that:

* **An API key**, when one is configured. Not a user system. It is the control
  that stops a public URL being an open write endpoint, and nothing more.
* **A body size ceiling**, because the plan endpoints take a JSON body and a
  large one costs real solver time before it is rejected.
* **CORS**, off unless origins are named, because a wildcard on a service that
  accepts writes is not a default anybody should inherit.

Every one of these is a deployment decision, so every one of them is a setting.
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backpacking.config import Settings

API_KEY_HEADER = "x-api-key"

#: Paths that answer without a key, so a load balancer can still probe them.
UNAUTHENTICATED_PATHS = frozenset({"/health", "/ready", "/metrics"})

#: Documentation paths, which follow the key only when one is configured.
DOC_PATHS = frozenset({"/docs", "/redoc", "/openapi.json"})


def keys_match(supplied: str | None, expected: str) -> bool:
    """Constant time comparison, so the check does not leak the key's prefix."""
    if not supplied:
        return False
    return hmac.compare_digest(supplied, expected)


def requires_key(path: str) -> bool:
    """Whether a path is behind the key when one is configured."""
    return path not in UNAUTHENTICATED_PATHS


def install_api_key(app: FastAPI, settings: Settings) -> bool:
    """Attach key checking. Returns whether it was actually turned on."""
    expected = settings.api_key
    if not expected:
        return False

    @app.middleware("http")
    async def _check_key(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not requires_key(request.url.path):
            return await call_next(request)
        if keys_match(request.headers.get(API_KEY_HEADER), expected):
            return await call_next(request)
        return JSONResponse(
            status_code=401,
            content={
                "code": "unauthorized",
                "message": f"supply a valid {API_KEY_HEADER} header",
                "context": {},
            },
        )

    return True


def install_body_limit(app: FastAPI, settings: Settings) -> None:
    """Reject an oversized body on the declared length, before reading it."""
    ceiling = settings.max_request_bytes

    @app.middleware("http")
    async def _limit_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        "code": "bad_content_length",
                        "message": "content-length is not a number",
                        "context": {"content_length": declared},
                    },
                )
            if length > ceiling:
                return JSONResponse(
                    status_code=413,
                    content={
                        "code": "request_too_large",
                        "message": "request body is larger than this service accepts",
                        "context": {"limit_bytes": ceiling, "declared_bytes": length},
                    },
                )
        return await call_next(request)


def install_cors(app: FastAPI, settings: Settings) -> bool:
    """Attach CORS only when origins are named. Returns whether it was added."""
    origins = [origin.strip() for origin in settings.cors_origins if origin.strip()]
    if not origins:
        return False
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["content-type", API_KEY_HEADER],
        max_age=600,
    )
    return True


def install_security_headers(app: FastAPI) -> None:
    """The handful of headers that are worth setting on a JSON API."""

    @app.middleware("http")
    async def _headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("x-content-type-options", "nosniff")
        response.headers.setdefault("referrer-policy", "no-referrer")
        response.headers.setdefault("cache-control", "no-store")
        return response
