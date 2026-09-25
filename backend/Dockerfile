# TrustTable backend image (FND-01, repository-foundation stage).
#
# Multi-stage build: install dependencies with uv into a virtual
# environment, then run the FastAPI app under Uvicorn as a non-root user.
# No product code, persistence, or AI path exists at this stage.

FROM python:3.14.6-slim-bookworm AS base

# Pinned uv release matching the version used for local development.
COPY --from=ghcr.io/astral-sh/uv:0.12.1 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# Install dependencies first (better layer caching), then the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY README.md ./
COPY src ./src
COPY alembic.ini ./
COPY alembic ./alembic
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app \
    # `DB-01`: pre-create `/data` (`Settings.data_directory`'s own
    # default) owned by `appuser` before `docker-compose.yml`'s named
    # volume is mounted there. Docker initializes an empty named volume's
    # content *and permissions* from the image directory it is mounted
    # over on first creation; without this, the volume mount is created
    # root-owned and the non-root `appuser` process cannot open the
    # SQLite file under it (`sqlite3.OperationalError: unable to open
    # database file` — reproduced against a real Compose stack).
    && mkdir -p /data && chown appuser:appuser /data
USER appuser

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

# `--factory`: `create_app()` (`DB-01`) now has a genuine, non-trivial
# side effect (building the database engine and running migrations), so
# it must run exactly once, at actual process startup, rather than as an
# eagerly-imported module attribute (see `main.py`'s own docstring).
CMD ["uvicorn", "trusttable_backend.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
