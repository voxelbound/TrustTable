"""Typed, validated application configuration (FND-02).

`Settings` is the runtime source of truth for every variable documented
in `.env.example` (23 variables, WP-002 provenance). `.env.example`
documents these defaults for humans; it is not read by the application.
An optional `.env` file at the repository root is read if present, purely
as a native-development convenience — its absence is not an error, and
`docker-compose.yml` does not require it either (WP-002 AC-03/AC-06).

Loading `Settings()` with an invalid value raises `pydantic.ValidationError`
immediately, which is intended to stop the process at startup (WP-002
AC-04) rather than allow the application to run with unvalidated
configuration. `database_url` and `llm_base_url` are excluded from the
default `repr()` because a future non-SQLite/non-local value could embed
credentials (WP-002 AC-10) — no code path in this package logs or
serializes the complete `Settings` object.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, NonNegativeInt, PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["development", "test", "production"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LlmProvider = Literal["disabled", "mock", "ollama"]

# backend/src/trusttable_backend/config.py -> repository root is four
# levels up. In a Docker image this resolves to a path outside the
# copied build context (e.g. container "/"), where no .env file exists
# either — the optional-file behavior below handles both cases safely.
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """One field per `.env.example` variable, grouped to match it exactly."""

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: AppEnv = "development"
    log_level: LogLevel = "INFO"
    database_url: Annotated[str, Field(min_length=1, repr=False)] = "sqlite:////data/trusttable.db"
    data_directory: Annotated[str, Field(min_length=1)] = "/data"

    # Local limits
    max_file_size_mb: PositiveInt = 100
    max_rows: PositiveInt = 1_000_000
    max_columns: PositiveInt = 500
    max_worksheets: PositiveInt = 20
    max_uncompressed_workbook_mb: PositiveInt = 500
    max_cell_count: PositiveInt = 50_000_000
    analysis_retention_hours: NonNegativeInt = 0
    background_worker_count: PositiveInt = 2

    # LLM provider
    llm_provider: LlmProvider = "disabled"
    llm_base_url: Annotated[str, Field(min_length=1, repr=False)] = (
        "http://host.docker.internal:11434"
    )
    llm_model: str = ""
    llm_temperature: Annotated[float, Field(ge=0, le=2)] = 0.0
    llm_context_window: PositiveInt = 8192
    llm_timeout_seconds: PositiveInt = 120
    llm_send_sample_values: bool = False
    llm_max_sample_values: NonNegativeInt = 10

    # Security
    prompt_injection_detection_enabled: bool = True
    max_text_value_length_for_analysis: PositiveInt = 10_000
    max_column_name_length: PositiveInt = 256


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached `Settings` instance.

    Raises `pydantic.ValidationError` on first call if any value is
    invalid — intended to be triggered at application startup (see
    `main.create_app`), not deferred to first request handling.
    """
    return Settings()
