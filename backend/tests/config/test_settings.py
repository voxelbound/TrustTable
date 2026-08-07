"""Typed configuration tests (WP-002 FND-02).

Table-driven per semantic group, per WP-002's "Validation semantics and
test design": every constrained field is individually parameterized
within its group so no field is covered only by a "representative" case.
Groups with a single field (the three enums and the bounded float) get
their own dedicated test.

`Settings(_env_file=None, ...)` is used throughout so these tests never
depend on whether a real `.env` happens to exist on the machine running
them — construction arguments and monkeypatched environment variables are
the only inputs, keeping the tests deterministic.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from trusttable_backend.config import Settings, get_settings
from trusttable_backend.main import create_app

# Every `.env.example` variable, verified 2026-08-07 against the file
# directly (23 total: 4 Application + 8 Local limits + 8 LLM provider +
# 3 Security).
ALL_ENV_VAR_NAMES = [
    "APP_ENV",
    "LOG_LEVEL",
    "DATABASE_URL",
    "DATA_DIRECTORY",
    "MAX_FILE_SIZE_MB",
    "MAX_ROWS",
    "MAX_COLUMNS",
    "MAX_WORKSHEETS",
    "MAX_UNCOMPRESSED_WORKBOOK_MB",
    "MAX_CELL_COUNT",
    "ANALYSIS_RETENTION_HOURS",
    "BACKGROUND_WORKER_COUNT",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "LLM_CONTEXT_WINDOW",
    "LLM_TIMEOUT_SECONDS",
    "LLM_SEND_SAMPLE_VALUES",
    "LLM_MAX_SAMPLE_VALUES",
    "PROMPT_INJECTION_DETECTION_ENABLED",
    "MAX_TEXT_VALUE_LENGTH_FOR_ANALYSIS",
    "MAX_COLUMN_NAME_LENGTH",
]
assert len(ALL_ENV_VAR_NAMES) == 23

EXPECTED_DEFAULTS = {
    "app_env": "development",
    "log_level": "INFO",
    "database_url": "sqlite:////data/trusttable.db",
    "data_directory": "/data",
    "max_file_size_mb": 100,
    "max_rows": 1_000_000,
    "max_columns": 500,
    "max_worksheets": 20,
    "max_uncompressed_workbook_mb": 500,
    "max_cell_count": 50_000_000,
    "analysis_retention_hours": 0,
    "background_worker_count": 2,
    "llm_provider": "disabled",
    "llm_base_url": "http://host.docker.internal:11434",
    "llm_model": "",
    "llm_temperature": 0.0,
    "llm_context_window": 8192,
    "llm_timeout_seconds": 120,
    "llm_send_sample_values": False,
    "llm_max_sample_values": 10,
    "prompt_injection_detection_enabled": True,
    "max_text_value_length_for_analysis": 10_000,
    "max_column_name_length": 256,
}
assert set(EXPECTED_DEFAULTS) == set(Settings.model_fields)

POSITIVE_INT_FIELDS = [
    "max_file_size_mb",
    "max_rows",
    "max_columns",
    "max_worksheets",
    "max_uncompressed_workbook_mb",
    "max_cell_count",
    "background_worker_count",
    "llm_context_window",
    "llm_timeout_seconds",
    "max_text_value_length_for_analysis",
    "max_column_name_length",
]
assert len(POSITIVE_INT_FIELDS) == 11

NON_NEGATIVE_INT_FIELDS = ["analysis_retention_hours", "llm_max_sample_values"]
BOOLEAN_FIELDS = ["llm_send_sample_values", "prompt_injection_detection_enabled"]
NON_EMPTY_STRING_FIELDS = ["database_url", "data_directory", "llm_base_url"]

SENTINEL_SECRET = "SENTINEL_zK9v3pQXLM_do_not_leak"


def _clear_all_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ALL_ENV_VAR_NAMES:
        monkeypatch.delenv(name, raising=False)


# --- AC-01 / AC-03: defaults match .env.example, no .env file required ---


def test_defaults_match_env_example_with_no_env_and_no_env_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all_env(monkeypatch)

    settings = Settings(_env_file=None)

    for field, expected in EXPECTED_DEFAULTS.items():
        assert getattr(settings, field) == expected, field


# --- AC-02: table-driven enforcement, one test per semantic group ---


@pytest.mark.parametrize("value", ["staging", "", "DEVELOPMENT", "prod"])
def test_app_env_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env=value)


@pytest.mark.parametrize("value", ["development", "test", "production"])
def test_app_env_accepts_documented_values(value: str) -> None:
    assert Settings(_env_file=None, app_env=value).app_env == value


@pytest.mark.parametrize("value", ["openai", "", "OLLAMA", "azure"])
def test_llm_provider_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider=value)


@pytest.mark.parametrize("value", ["disabled", "mock", "ollama"])
def test_llm_provider_accepts_documented_values(value: str) -> None:
    assert Settings(_env_file=None, llm_provider=value).llm_provider == value


@pytest.mark.parametrize("value", ["TRACE", "", "info", "NOTSET"])
def test_log_level_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level=value)


@pytest.mark.parametrize("value", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_log_level_accepts_documented_values(value: str) -> None:
    assert Settings(_env_file=None, log_level=value).log_level == value


@pytest.mark.parametrize("field", BOOLEAN_FIELDS)
@pytest.mark.parametrize("value", ["maybe", "2", "yes-ish"])
def test_boolean_fields_reject_invalid_values(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


@pytest.mark.parametrize("field", BOOLEAN_FIELDS)
@pytest.mark.parametrize("value", ["true", "false"])
def test_boolean_fields_accept_documented_values(field: str, value: str) -> None:
    settings = Settings.model_validate({field: value})
    assert getattr(settings, field) is (value == "true")


@pytest.mark.parametrize("field", POSITIVE_INT_FIELDS)
@pytest.mark.parametrize("value", [0, -1, "abc"])
def test_positive_int_fields_reject_invalid_values(field: str, value: int | str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


@pytest.mark.parametrize("field", POSITIVE_INT_FIELDS)
def test_positive_int_fields_accept_one(field: str) -> None:
    assert getattr(Settings.model_validate({field: 1}), field) == 1


@pytest.mark.parametrize("field", NON_NEGATIVE_INT_FIELDS)
@pytest.mark.parametrize("value", [-1, "abc"])
def test_non_negative_int_fields_reject_invalid_values(field: str, value: int | str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


@pytest.mark.parametrize("field", NON_NEGATIVE_INT_FIELDS)
def test_non_negative_int_fields_accept_zero(field: str) -> None:
    assert getattr(Settings.model_validate({field: 0}), field) == 0


@pytest.mark.parametrize("field", NON_EMPTY_STRING_FIELDS)
def test_non_empty_string_fields_reject_empty_string(field: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: ""})


@pytest.mark.parametrize("field", NON_EMPTY_STRING_FIELDS)
def test_non_empty_string_fields_accept_non_empty(field: str) -> None:
    assert getattr(Settings.model_validate({field: "x"}), field) == "x"


@pytest.mark.parametrize("value", [-0.1, 2.1, "abc"])
def test_llm_temperature_rejects_invalid_values(value: float | str) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_temperature=value)


@pytest.mark.parametrize("value", [0, 2, 1.5])
def test_llm_temperature_accepts_boundary_and_mid_values(value: float) -> None:
    assert Settings(_env_file=None, llm_temperature=value).llm_temperature == value


def test_llm_model_accepts_any_string_including_empty() -> None:
    assert Settings(_env_file=None, llm_model="").llm_model == ""
    assert Settings(_env_file=None, llm_model="llama3").llm_model == "llama3"


# --- AC-04: invalid config fails startup (create_app), one representative
#     case per group is sufficient here since per-field enforcement is
#     already proven above; this proves the *startup* wiring, not the
#     field-level rule. ---


def test_invalid_app_env_fails_create_app(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "not-a-real-mode")
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        create_app()


# --- AC-05: valid overrides apply, one representative case per group ---


def test_overrides_apply_per_group(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PROMPT_INJECTION_DETECTION_ENABLED", "false")
    monkeypatch.setenv("MAX_ROWS", "42")
    monkeypatch.setenv("LLM_MAX_SAMPLE_VALUES", "0")
    monkeypatch.setenv("DATA_DIRECTORY", "/custom/data")
    monkeypatch.setenv("LLM_TEMPERATURE", "1.25")
    monkeypatch.setenv("LLM_MODEL", "custom-model")

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.llm_provider == "mock"
    assert settings.log_level == "DEBUG"
    assert settings.prompt_injection_detection_enabled is False
    assert settings.max_rows == 42
    assert settings.llm_max_sample_values == 0
    assert settings.data_directory == "/custom/data"
    assert settings.llm_temperature == 1.25
    assert settings.llm_model == "custom-model"


# --- AC-10: no code path logs/serializes the complete Settings object;
#     validation/startup errors and successful load never expose a
#     sensitive DATABASE_URL value. ---


def test_database_url_sentinel_absent_from_unrelated_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("MAX_ROWS", "not-a-number")

    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            database_url=f"postgresql://user:{SENTINEL_SECRET}@host/db",
        )

    assert SENTINEL_SECRET not in str(exc_info.value)


def test_database_url_sentinel_absent_from_repr_and_str_on_success() -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"postgresql://user:{SENTINEL_SECRET}@host/db",
    )

    assert SENTINEL_SECRET not in repr(settings)
    assert SENTINEL_SECRET not in str(settings)


def test_llm_base_url_sentinel_absent_from_repr() -> None:
    settings = Settings(
        _env_file=None,
        llm_base_url=f"http://user:{SENTINEL_SECRET}@host:11434",
    )

    assert SENTINEL_SECRET not in repr(settings)


def test_database_url_sentinel_absent_from_api_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_all_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", f"postgresql://user:{SENTINEL_SECRET}@host/db")
    get_settings.cache_clear()

    with TestClient(create_app()) as test_client:
        version_text = test_client.get("/api/v1/version").text
        ready_text = test_client.get("/api/v1/health/ready").text

    assert SENTINEL_SECRET not in version_text
    assert SENTINEL_SECRET not in ready_text
