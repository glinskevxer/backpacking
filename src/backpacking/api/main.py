"""Module level application object for a uvicorn or gunicorn command line.

Anything that can pass arguments should call
:func:`backpacking.api.app.create_app` instead.
"""

from __future__ import annotations

from backpacking.api.app import create_app

app = create_app()
