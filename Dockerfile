# Multi stage. The build stage keeps the toolchain, the runtime stage does not,
# which is the difference between a 900 MB image and a 190 MB one.

FROM python:3.15-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && /opt/venv/bin/pip install ".[api,db,cli]"


FROM python:3.15-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    BACKPACKING_LOG_JSON=true

# Run as a non root user. The image writes nothing outside /tmp, so the home
# directory exists only to give pip and python somewhere to look.
RUN groupadd --system --gid 1001 trail \
    && useradd --system --uid 1001 --gid trail --create-home --home-dir /home/trail trail

COPY --from=build /opt/venv /opt/venv
COPY --chown=trail:trail migrations /app/migrations
COPY --chown=trail:trail alembic.ini /app/alembic.ini

WORKDIR /app
USER trail

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "backpacking.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
