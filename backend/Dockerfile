# AFTERMATH API. SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.
# Build context: the repository root (the API reads ../data at runtime).
#   docker build -f backend/Dockerfile -t aftermath-api .

FROM python:3.13.9-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend
# Dependencies first (cached layer), from the committed lockfile only.
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
RUN uv sync --frozen --no-dev

# Test image (dev dependencies and tests), for hosts that cannot run the suite natively:
#   docker build -f backend/Dockerfile --target test -t aftermath-api:test .
FROM build AS test
RUN uv sync --frozen
COPY backend/tests ./tests
COPY backend/scripts ./scripts
COPY backend/alembic.ini ./alembic.ini
COPY backend/migrations ./migrations
COPY data /srv/data
ENV PATH="/srv/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["python", "-m", "pytest", "-q"]

FROM python:3.13.9-slim-bookworm AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PATH="/srv/backend/.venv/bin:$PATH"
RUN groupadd --system app && useradd --system --gid app --home /srv app
WORKDIR /srv/backend
COPY --from=build --chown=app:app /srv/backend /srv/backend
COPY --chown=app:app backend/alembic.ini ./alembic.ini
COPY --chown=app:app backend/migrations ./migrations
COPY --chown=app:app data /srv/data
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2).status == 200 else 1)"
# One worker: background agent workflows and the SSE event bus live in this process (ADR-0006).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
