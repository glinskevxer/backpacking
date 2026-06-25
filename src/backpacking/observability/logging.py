"""Structured logging.

Two output shapes, chosen by configuration rather than by guesswork:

* A console renderer for a terminal, because a human reading a CLI run wants
  lines, not JSON.
* A JSON renderer everywhere else, because the log ends up in something that
  parses it, and a message that has to be regex matched back apart is a message
  that will be parsed wrongly during the one incident it mattered.

The context variable machinery is what carries a request id from the middleware
down into the query log without threading it through every function signature.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    clear_contextvars,
    merge_contextvars,
    unbind_contextvars,
)

from backpacking.config import Settings

#: Keys that must never reach a log line, whatever a caller passes.
REDACTED_KEYS = frozenset({"password", "token", "secret", "authorization", "api_key"})
REDACTION = "[redacted]"


def redact_processor(
    _logger: object, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Replace anything that looks like a credential before it is rendered."""
    for key in list(event):
        if key.lower() in REDACTED_KEYS:
            event[key] = REDACTION
    return event


def add_service_name(
    _logger: object, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event.setdefault("service", "backpacking")
    return event


def configure_logging(settings: Settings | None = None, *, force: bool = False) -> None:
    """Configure structlog and the standard library handler behind it."""
    from backpacking.config import get_settings

    resolved = settings or get_settings()
    if structlog.is_configured() and not force:
        return
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, resolved.log_level),
        force=True,
    )
    shared: list[Any] = [
        merge_contextvars,
        add_service_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        redact_processor,
    ]
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if resolved.log_json
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, resolved.log_level)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """A bound logger for one module."""
    return structlog.get_logger(name)


def bind_request(request_id: str, **extra: Any) -> None:
    """Attach a request id, and anything else, to everything logged after this."""
    bind_contextvars(request_id=request_id, **extra)


def clear_request() -> None:
    clear_contextvars()


def unbind(*keys: str) -> None:
    unbind_contextvars(*keys)
