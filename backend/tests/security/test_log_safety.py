"""Logging-safety tests (SEC-01, scoped, WP-032).

`docs/security-threat-model.md` §5 ("Logging") requires that logs never
contain raw rows, full suspicious text, full prompts with dataset
samples, or secrets, and `docs/testing-strategy.md` §7 lists "secrets
absent from logs" as a required security-test category. No test
anywhere in this repository previously exercised the application's own
logging behavior (grep-confirmed before this package). These tests
close that gap for the one real production logging call-site.

Scope and an honest limitation: `main.py`'s `logger.exception(...)`
necessarily logs the raised exception's own traceback (Python's
standard `logging.Logger.exception` behavior) — these tests cannot and
do not claim that no future exception message could ever embed raw
dataset content; that remains a coding-discipline concern, not an
enforced boundary, absent a dedicated log-redaction layer (out of this
package's scope, recorded in `WP-032-v01-security-qualification.md`'s
Recorded assumption 2). What these tests do prove, structurally and
behaviorally, is that the *fixed* portion of the log record — the
message itself and its `extra` fields — never varies with, or embeds,
request/exception content: it is always the literal string
`"unhandled exception"` plus a generated `request_id`.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trusttable_backend.main import register_exception_handlers
from trusttable_backend.request_context import REQUEST_ID_HEADER, RequestIdMiddleware

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "src" / "trusttable_backend"
_MAIN_MODULE_PATH = _BACKEND_SRC / "main.py"

_MARKER = "raw-dataset-row-marker-9f21ac"


# ---------------------------------------------------------------------------
# AC-01: exactly one logger.* call-site exists in backend/src
# ---------------------------------------------------------------------------


def _find_logger_calls(tree: ast.Module) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            calls.append(node)
    return calls


def test_exactly_one_logger_call_site_exists_in_backend_source() -> None:
    call_sites: list[tuple[Path, ast.Call]] = []
    for path in sorted(_BACKEND_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for call in _find_logger_calls(tree):
            call_sites.append((path, call))

    assert len(call_sites) == 1, (
        f"expected exactly one logger.* call-site under {_BACKEND_SRC}, found "
        f"{len(call_sites)}: {[str(path) for path, _ in call_sites]}"
    )
    only_path, _ = call_sites[0]
    assert only_path == _MAIN_MODULE_PATH


# ---------------------------------------------------------------------------
# AC-02: that call-site's message is a fixed literal; extra has only request_id
# ---------------------------------------------------------------------------


def test_unhandled_exception_handler_uses_fixed_safe_message_and_only_request_id_extra() -> None:
    tree = ast.parse(_MAIN_MODULE_PATH.read_text(encoding="utf-8"), filename=str(_MAIN_MODULE_PATH))
    calls = _find_logger_calls(tree)
    assert len(calls) == 1
    call = calls[0]

    # First positional argument must be a plain string constant, never an
    # f-string/JoinedStr or any interpolation of exception/request content.
    assert len(call.args) == 1
    message_node = call.args[0]
    assert isinstance(message_node, ast.Constant)
    assert isinstance(message_node.value, str)
    assert message_node.value == "unhandled exception"

    # `extra=` must be exactly {"request_id": ...} — no other field, and in
    # particular nothing derived from `exc` or from any request body/dataset
    # content.
    extra_keywords = [kw for kw in call.keywords if kw.arg == "extra"]
    assert len(extra_keywords) == 1
    extra_value = extra_keywords[0].value
    assert isinstance(extra_value, ast.Dict)
    assert len(extra_value.keys) == 1
    key_node = extra_value.keys[0]
    assert isinstance(key_node, ast.Constant)
    assert key_node.value == "request_id"


# ---------------------------------------------------------------------------
# AC-03: behavioral proof — the real emitted log record matches the above
# ---------------------------------------------------------------------------


def _build_log_safety_test_app() -> FastAPI:
    """An isolated app wired with the real handlers plus one throwaway route.

    Mirrors `backend/tests/api/test_errors.py`'s `_build_error_test_app`
    pattern exactly (`FND-04`), reusing the real `register_exception_handlers`
    rather than a parallel reimplementation.
    """
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/boom/raw-content")
    def _raise_with_marker() -> None:
        # Simulates a hypothetical future defect where an unexpected
        # exception's own message embeds dataset-like content. The fixed
        # "unhandled exception" log message (asserted below) never
        # includes this text; only Python's own traceback rendering of
        # `exc` would (an inherent, disclosed characteristic of
        # `logger.exception`, not something this test can or should hide).
        raise ValueError(_MARKER)

    return app


@pytest.fixture
def log_safety_client() -> TestClient:
    return TestClient(_build_log_safety_test_app(), raise_server_exceptions=False)


def test_unhandled_exception_route_logs_fixed_message_with_real_request_id(
    log_safety_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="trusttable_backend.main"):
        response = log_safety_client.get(
            "/boom/raw-content", headers={REQUEST_ID_HEADER: "corr-log-safety-test"}
        )

    assert response.status_code == 500

    matching = [record for record in caplog.records if record.name == "trusttable_backend.main"]
    assert len(matching) == 1
    record = matching[0]

    # The fixed message portion never varies with, or embeds, the raised
    # exception's own content.
    assert record.getMessage() == "unhandled exception"
    assert getattr(record, "request_id", None) == "corr-log-safety-test"
