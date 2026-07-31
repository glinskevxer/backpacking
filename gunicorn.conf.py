"""Gunicorn configuration for the deployed service.

Uvicorn alone is right for development and wrong for production: it is one
process, so one slow request blocks the loop and a crash takes the service with
it. Gunicorn supervises several uvicorn workers instead, restarts them when they
die, and recycles them before a slow leak matters.

The numbers are chosen for a container with a CPU limit rather than for a bare
machine, which is why the worker count comes from the cgroup quota and not from
``os.cpu_count``.
"""

from __future__ import annotations

import os
import pathlib

#: Where the cgroup v2 CPU quota lives inside a container.
CPU_MAX = pathlib.Path("/sys/fs/cgroup/cpu.max")

#: Never fewer than this many workers, and never more, whatever the box says.
MIN_WORKERS = 2
MAX_WORKERS = 12


def available_cpus() -> float:
    """CPUs this process may actually use, honouring a container limit."""
    try:
        quota, period = CPU_MAX.read_text().split()
    except (OSError, ValueError):
        return float(os.cpu_count() or 1)
    if quota == "max":
        return float(os.cpu_count() or 1)
    try:
        return max(1.0, float(quota) / float(period))
    except (ValueError, ZeroDivisionError):
        return float(os.cpu_count() or 1)


def worker_count() -> int:
    """Two per usable CPU plus one, clamped, which is the usual starting point."""
    configured = os.environ.get("BACKPACKING_WORKERS")
    if configured:
        try:
            return max(1, int(configured))
        except ValueError:
            pass
    suggested = int(available_cpus() * 2) + 1
    return max(MIN_WORKERS, min(MAX_WORKERS, suggested))


bind = os.environ.get("BACKPACKING_BIND", "0.0.0.0:8000")
workers = worker_count()
worker_class = "uvicorn.workers.UvicornWorker"

# The solver holds the loop for a few hundred milliseconds on a long corridor,
# so the timeout has to be well clear of that without hiding a genuine hang.
timeout = int(os.environ.get("BACKPACKING_TIMEOUT", "60"))
graceful_timeout = 30
keepalive = 5

# Recycle workers so a slow leak never becomes an incident. The jitter stops
# every worker recycling on the same request.
max_requests = 2000
max_requests_jitter = 250

# Logs go to stdout and are already structured by the application, so gunicorn's
# own access log is turned off rather than duplicated in a different shape.
accesslog = None
errorlog = "-"
loglevel = os.environ.get("BACKPACKING_LOG_LEVEL", "info").lower()

# Preload so the workers share the import cost and the parsed corridor code.
# Safe here because nothing is opened at import time; the database engine is
# built inside the lifespan, per worker.
preload_app = True

proc_name = "backpacking"


def on_starting(server: object) -> None:
    """Announce the shape of the deployment once, before any worker starts."""
    print(f"backpacking starting with {workers} workers on {bind}", flush=True)


def worker_int(worker: object) -> None:
    """Log the worker that was interrupted, which is otherwise silent."""
    print(f"worker {getattr(worker, 'pid', '?')} interrupted", flush=True)
