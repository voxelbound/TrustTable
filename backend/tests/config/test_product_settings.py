"""Product settings: the allowlist, the precedence rule and the store (`UX-08a`).

The decisive proofs of the package's intent (D-066 item 5):

- an override is an *explicitly configured* `LLM_PROVIDER`, never a value that
  merely equals the default, and it comes from the environment or `.env`;
- a stored value never exceeds an override;
- the allowlist is closed and typed, and a stale write changes nothing;
- packaging (`.env.example` and Compose) sets no managed key.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from trusttable_backend.config import Settings
from trusttable_backend.persistence import run_migrations
from trusttable_backend.persistence.settings_store import (
    SettingsVersionConflictError,
    SqlSettingsStore,
)
from trusttable_backend.product_settings import (
    AI_ASSISTANCE_KEY,
    ALLOWED_SETTINGS,
    InvalidSettingValueError,
    UnknownSettingError,
    is_deployment_override,
    resolve_ai_assistance,
    validate_setting,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _settings(**values: object) -> Settings:
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


# --- the allowlist is closed and typed ---------------------------------------


def test_the_allowlist_is_exactly_one_boolean_key() -> None:
    assert {"ai_assistance": bool} == ALLOWED_SETTINGS


@pytest.mark.parametrize("value", [True, False])
def test_a_boolean_is_accepted(value: bool) -> None:
    assert validate_setting(AI_ASSISTANCE_KEY, value) is value


@pytest.mark.parametrize("value", [1, 0, "true", "false", None, 1.0, [], {}])
def test_anything_that_is_not_exactly_a_boolean_is_rejected(value: object) -> None:
    with pytest.raises(InvalidSettingValueError):
        validate_setting(AI_ASSISTANCE_KEY, value)


@pytest.mark.parametrize(
    "key", ["", "llm_provider", "max_file_size_mb", "database_url", "ai_profile", "AI_ASSISTANCE"]
)
def test_an_unknown_key_is_rejected(key: str) -> None:
    with pytest.raises(UnknownSettingError):
        validate_setting(key, True)


def test_no_limit_path_url_or_secret_setting_is_on_the_allowlist() -> None:
    forbidden = ("max_", "url", "path", "directory", "secret", "key", "retention", "delete")
    for key in ALLOWED_SETTINGS:
        assert not any(word in key for word in forbidden), key


# --- an override is explicit, never inferred ---------------------------------


def test_a_default_is_not_an_override() -> None:
    assert is_deployment_override(_settings()) is False


def test_an_explicit_value_equal_to_the_default_is_still_an_override() -> None:
    # Override detection never compares a value with its default.
    settings = _settings(llm_provider="disabled")
    assert settings.llm_provider == Settings.model_fields["llm_provider"].default
    assert is_deployment_override(settings) is True


def test_an_environment_variable_is_an_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    assert is_deployment_override(Settings(_env_file=None)) is True


def test_an_env_file_value_is_an_override(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_PROVIDER=disabled\n", encoding="utf-8")
    assert is_deployment_override(Settings(_env_file=env_file)) is True


def test_other_llm_values_in_the_environment_are_not_an_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL", "model-a")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8081")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "30")
    assert is_deployment_override(Settings(_env_file=None)) is False


# --- precedence: override, then stored, then default -------------------------


def test_the_default_is_off_and_not_managed() -> None:
    resolution = resolve_ai_assistance(_settings(), None)
    assert (resolution.enabled, resolution.source, resolution.managed) == (False, "default", False)
    assert resolution.settings.llm_provider == "disabled"


def test_a_stored_off_is_off_from_the_stored_source() -> None:
    resolution = resolve_ai_assistance(_settings(llm_model="m"), False)
    assert (resolution.enabled, resolution.source, resolution.managed) == (False, "stored", False)
    assert resolution.settings.llm_provider == "disabled"


def test_a_stored_on_with_a_configured_model_selects_the_local_runtime() -> None:
    resolution = resolve_ai_assistance(_settings(llm_model="model-a"), True)
    assert (resolution.enabled, resolution.source, resolution.managed) == (True, "stored", False)
    assert resolution.runtime_configured is True
    assert resolution.settings.llm_provider == "llama_cpp"
    assert resolution.settings.llm_model == "model-a"


@pytest.mark.parametrize("model", ["", "   "])
def test_a_stored_on_without_a_model_is_on_but_nothing_can_run(model: str) -> None:
    resolution = resolve_ai_assistance(_settings(llm_model=model), True)
    assert (resolution.enabled, resolution.runtime_configured) == (True, False)
    assert resolution.settings.llm_provider == "disabled"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://10.9.8.7:8081",
        "http://models.example.invalid",
        "https://203.0.113.4:443",
        "not a url",
    ],
)
def test_a_stored_on_with_a_model_but_a_non_local_address_cannot_run(base_url: str) -> None:
    resolution = resolve_ai_assistance(_settings(llm_model="model-a", llm_base_url=base_url), True)

    assert (resolution.enabled, resolution.runtime_configured) == (True, False)
    assert resolution.unavailable_reason == "not_local"
    assert resolution.settings.llm_provider == "disabled"


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:8081",
        "http://127.0.0.1:9",
        "http://[::1]:8081",
        "http://host.docker.internal",
    ],
)
def test_a_stored_on_with_a_model_and_a_local_address_runs(base_url: str) -> None:
    resolution = resolve_ai_assistance(_settings(llm_model="model-a", llm_base_url=base_url), True)

    assert (resolution.runtime_configured, resolution.unavailable_reason) == (True, None)
    assert resolution.settings.llm_provider == "llama_cpp"


def test_a_stored_on_without_a_model_says_why() -> None:
    assert resolve_ai_assistance(_settings(), True).unavailable_reason == "no_runtime"


@pytest.mark.parametrize("stored", [None, True, False])
@pytest.mark.parametrize("provider", ["disabled", "mock", "llama_cpp"])
def test_a_stored_value_never_exceeds_an_explicit_override(
    provider: str, stored: bool | None
) -> None:
    settings = _settings(llm_provider=provider, llm_model="model-a")

    resolution = resolve_ai_assistance(settings, stored)

    assert resolution.managed is True and resolution.source == "deployment"
    assert resolution.enabled is (provider != "disabled")
    assert resolution.settings.llm_provider == provider


def test_an_override_of_disabled_wins_over_a_stored_on() -> None:
    resolution = resolve_ai_assistance(_settings(llm_provider="disabled", llm_model="m"), True)
    assert resolution.enabled is False
    assert resolution.settings.llm_provider == "disabled"


def test_resolution_leaves_the_deployment_settings_untouched() -> None:
    settings = _settings(llm_model="model-a")
    resolve_ai_assistance(settings, True)
    assert settings.llm_provider == "disabled"


# --- the store ---------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SqlSettingsStore:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")
    run_migrations(Settings(_env_file=None))
    return SqlSettingsStore(create_engine(f"sqlite:///{tmp_path / 'store.db'}"))


def test_the_migration_creates_the_settings_table(store: SqlSettingsStore, tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'store.db'}")
    columns = {column["name"] for column in inspect(engine).get_columns("app_settings")}
    assert columns == {"key", "value_json", "version", "updated_at"}


def test_a_key_never_written_has_no_value_and_version_zero(store: SqlSettingsStore) -> None:
    stored = store.get(AI_ASSISTANCE_KEY)
    assert (stored.value, stored.version) == (None, 0)


def test_a_write_stores_the_value_and_advances_the_version(store: SqlSettingsStore) -> None:
    first = store.put(AI_ASSISTANCE_KEY, True, expected_version=0)
    second = store.put(AI_ASSISTANCE_KEY, False, expected_version=1)

    assert (first.value, first.version) == (True, 1)
    assert (second.value, second.version) == (False, 2)
    assert store.get(AI_ASSISTANCE_KEY).value is False


def test_a_stale_version_changes_nothing(store: SqlSettingsStore) -> None:
    store.put(AI_ASSISTANCE_KEY, True, expected_version=0)

    with pytest.raises(SettingsVersionConflictError) as conflict:
        store.put(AI_ASSISTANCE_KEY, False, expected_version=0)

    assert conflict.value.actual_version == 1
    assert (store.get(AI_ASSISTANCE_KEY).value, store.get(AI_ASSISTANCE_KEY).version) == (True, 1)


def test_a_first_write_quoting_a_version_other_than_zero_is_refused(
    store: SqlSettingsStore,
) -> None:
    with pytest.raises(SettingsVersionConflictError):
        store.put(AI_ASSISTANCE_KEY, True, expected_version=3)
    assert store.get(AI_ASSISTANCE_KEY).version == 0


def test_a_reset_removes_the_value_and_a_version_never_repeats(store: SqlSettingsStore) -> None:
    store.put(AI_ASSISTANCE_KEY, True, expected_version=0)

    reset = store.reset(AI_ASSISTANCE_KEY, expected_version=1)

    assert (reset.value, reset.version) == (None, 2)
    assert store.get(AI_ASSISTANCE_KEY).value is None
    # A writer still holding the pre-reset version can never match an earlier state.
    with pytest.raises(SettingsVersionConflictError):
        store.put(AI_ASSISTANCE_KEY, True, expected_version=1)
    assert store.put(AI_ASSISTANCE_KEY, True, expected_version=2).version == 3


def test_the_store_itself_rejects_unknown_keys_and_wrong_types(store: SqlSettingsStore) -> None:
    with pytest.raises(UnknownSettingError):
        store.put("max_rows", 5, expected_version=0)
    with pytest.raises(UnknownSettingError):
        store.get("database_url")
    with pytest.raises(UnknownSettingError):
        store.reset("llm_base_url", expected_version=0)
    with pytest.raises(InvalidSettingValueError):
        store.put(AI_ASSISTANCE_KEY, "yes", expected_version=0)
    assert store.get(AI_ASSISTANCE_KEY).version == 0


def test_concurrent_writers_quoting_the_same_version_cannot_both_win(
    store: SqlSettingsStore,
) -> None:
    outcomes: list[str] = []
    gate = threading.Barrier(8)

    def write(value: bool) -> None:
        gate.wait()
        try:
            store.put(AI_ASSISTANCE_KEY, value, expected_version=0)
            outcomes.append("won")
        except SettingsVersionConflictError:
            outcomes.append("lost")

    threads = [threading.Thread(target=write, args=(index % 2 == 0,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("won") == 1 and outcomes.count("lost") == 7
    assert store.get(AI_ASSISTANCE_KEY).version == 1


# --- packaging creates no explicit override ----------------------------------


def _active_env_names(text: str) -> set[str]:
    return {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    }


def test_env_example_sets_no_managed_key_but_documents_it() -> None:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LLM_PROVIDER" not in _active_env_names(text)
    assert "# LLM_PROVIDER=disabled" in text.splitlines()
    # The plain explanation for an installation that copied the old file.
    assert "explicit" in text and "override" in text and "delete that line" in text


@pytest.mark.parametrize("compose", ["docker-compose.yml", "docker-compose.release.yml"])
def test_compose_files_set_no_managed_key(compose: str) -> None:
    text = (REPO_ROOT / compose).read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"\bLLM_PROVIDER\b", code, re.IGNORECASE)


def test_the_example_file_alone_creates_no_override(tmp_path: Path) -> None:
    # The decisive packaging proof: loading a copy of `.env.example` as-is is not an override.
    copy = tmp_path / ".env"
    copy.write_text((REPO_ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    assert is_deployment_override(Settings(_env_file=copy)) is False
