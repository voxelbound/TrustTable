"""The backend suite is hermetic against local configuration (FUP-013).

`Settings()` reads a repository-root `.env` and the process environment. The
autouse `_hermetic_settings` fixture in `tests/conftest.py` removes both for
each test, so a developer machine configured for a real provider gives the
same results as CI. These tests prove that fixture rather than assume it:

- in-process, that tests observe the documented defaults and can still
  configure `Settings` themselves;
- in a subprocess running the *real* conftest, that a deliberately polluted
  process environment and a polluted env file are both neutralized, with
  controls proving the pollution was genuinely present (so the assertion
  cannot pass vacuously).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from trusttable_backend.config import Settings, get_settings

_REAL_CONFTEST = Path(__file__).resolve().parents[1] / "conftest.py"

# Pollution that a developer machine configured for real local AI would carry.
_POLLUTED_ENVIRONMENT = {
    "LLM_PROVIDER": "llama_cpp",
    "llm_model": "/models/should-not-leak.gguf",  # lowercase: Settings is case-insensitive
    "LLM_TIMEOUT_SECONDS": "7",
}

# Appended *after* the real conftest source (which begins with a
# `from __future__` import that must stay first). Everything here runs at
# import time, before any fixture.
_SHIM = """\
# Simulates a developer machine.
import os
from pathlib import Path

from trusttable_backend.config import Settings

_ENV_FILE = Path(__file__).resolve().parent / "polluting.env"
_ENV_FILE.write_text("LLM_BASE_URL=http://pollution.invalid:1\\nLLM_TEMPERATURE=1.5\\n")
Settings.model_config["env_file"] = _ENV_FILE

# Recorded before any fixture runs, so the inner test can prove the pollution
# was genuinely present in the process when the fixture neutralized it.
POLLUTION_SEEN_AT_IMPORT = {
    "provider": os.environ.get("LLM_PROVIDER"),
    "model": os.environ.get("llm_model"),
    "timeout": os.environ.get("LLM_TIMEOUT_SECONDS"),
}
ENV_FILE_PATH = _ENV_FILE

"""

_INNER_TEST = """\
import os

import conftest
from trusttable_backend.config import Settings, get_settings


def test_pollution_was_real_and_is_neutralized() -> None:
    # Controls: the pollution existed when the session started ...
    assert conftest.POLLUTION_SEEN_AT_IMPORT == {
        "provider": "llama_cpp",
        "model": "/models/should-not-leak.gguf",
        "timeout": "7",
    }
    # ... and the env file genuinely carries values when read explicitly.
    polluted = Settings(_env_file=conftest.ENV_FILE_PATH)
    assert polluted.llm_temperature == 1.5
    assert polluted.llm_base_url == "http://pollution.invalid:1"

    # Yet under the fixture, both Settings() and get_settings() see defaults.
    for settings in (Settings(), get_settings()):
        assert settings.llm_provider == "disabled"
        assert settings.llm_model == ""
        assert settings.llm_timeout_seconds == 120
        assert settings.llm_temperature == 0.0
        assert settings.llm_base_url == "http://host.docker.internal:8081"
    assert "LLM_PROVIDER" not in os.environ
    assert "llm_model" not in os.environ
"""


def test_tests_observe_the_documented_defaults() -> None:
    settings = Settings()
    assert settings.llm_provider == "disabled"
    assert settings.llm_model == ""
    assert get_settings().llm_provider == "disabled"


def test_the_env_file_is_disabled_on_settings_during_tests() -> None:
    assert Settings.model_config.get("env_file") is None


def test_a_test_can_still_configure_settings_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "explicit-model")
    settings = Settings()
    assert settings.llm_provider == "mock"
    assert settings.llm_model == "explicit-model"


def test_an_explicit_env_file_is_still_honored(tmp_path: Path) -> None:
    env_file = tmp_path / "explicit.env"
    env_file.write_text("LLM_PROVIDER=mock\n")
    assert Settings(_env_file=env_file).llm_provider == "mock"


def test_a_polluted_environment_and_env_file_are_neutralized_by_the_real_conftest(
    tmp_path: Path,
) -> None:
    (tmp_path / "conftest.py").write_text(_REAL_CONFTEST.read_text() + "\n\n" + _SHIM)
    (tmp_path / "test_inner.py").write_text(_INNER_TEST)
    (tmp_path / "pytest.ini").write_text("[pytest]\n")

    environment = {
        key: value for key, value in os.environ.items() if key.lower() not in Settings.model_fields
    }
    environment.update(_POLLUTED_ENVIRONMENT)

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_inner.py"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
