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
RUN uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000

CMD ["uvicorn", "trusttable_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
