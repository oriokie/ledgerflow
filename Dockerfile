# syntax=docker/dockerfile:1
# Multi-stage build: the builder installs deps into a venv; the runtime image
# copies only that venv + source, so build tools never ship in production.

ARG PYTHON_VERSION=3.12-slim

# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS builder
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements/ requirements/
ARG REQUIREMENTS_FILE=requirements/production.txt
RUN pip install --upgrade pip && pip install -r ${REQUIREMENTS_FILE}

# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION} AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system app && adduser --system --ingroup app app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .

RUN mkdir -p /app/staticfiles /app/media && chown -R app:app /app/staticfiles /app/media

USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD curl -f http://localhost:8000/healthz/ || exit 1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "30"]
