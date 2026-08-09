"""Tests for the structured error envelope and request-ID layer (FND-04).

Positive, negative, and boundary paths per `docs/api-specification.md`
"Error format" / §14 / §15 and this package's acceptance criteria
(AC-01..AC-06). `AppError`, `RequestValidationError`, and unhandled
`Exception` paths are exercised against an isolated test app built from
the exact same `register_exception_handlers` the real app uses (no
production route currently accepts input that can trigger a validation
error or a business exception). The default-404 and request-ID
success-path checks use the real app via the shared `client` fixture
(`conftest.py`).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from trusttable_backend.errors import AppError
from trusttable_backend.main import register_exception_handlers
from trusttable_backend.request_context import REQUEST_ID_HEADER, RequestIdMiddleware

_SECRET_EXCEPTION_TEXT = "super-secret-internal-detail-4f8c1e"


def _build_error_test_app() -> FastAPI:
    """An isolated app wired with the real handlers plus throwaway routes.

    Never exposed by the production app (`create_app`) — exists only so
    the shared exception-handling code path can be exercised for cases no
    real endpoint triggers yet.
    """
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/boom/app-error")
    def _raise_app_error() -> None:
        raise AppError(
            "ANALYSIS_NOT_FOUND",
            "The requested analysis was not found.",
            status_code=404,
            details={"analysis_id": "abc-123"},
        )

    @app.get("/boom/validate")
    def _requires_query(count: int = Query(...)) -> dict[str, int]:
        return {"count": count}

    @app.get("/boom/unhandled")
    def _raise_unhandled() -> None:
        raise ValueError(_SECRET_EXCEPTION_TEXT)

    return app


@pytest.fixture
def error_client() -> TestClient:
    # `raise_server_exceptions=False`: the unhandled-exception path is
    # deliberately triggered here to assert on the resulting HTTP response,
    # not to have the test process re-raise it (Starlette's
    # ServerErrorMiddleware re-raises after sending the response).
    return TestClient(_build_error_test_app(), raise_server_exceptions=False)


# --- AC-01/AC-02: AppError -> exact envelope shape -------------------------


def test_app_error_returns_exact_status_and_envelope(error_client: TestClient) -> None:
    response = error_client.get("/boom/app-error")

    assert response.status_code == 404
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert set(body["error"].keys()) == {"code", "message", "details", "request_id"}
    assert body["error"]["code"] == "ANALYSIS_NOT_FOUND"
    assert body["error"]["message"] == "The requested analysis was not found."
    assert body["error"]["details"] == {"analysis_id": "abc-123"}
    assert isinstance(body["error"]["request_id"], str) and body["error"]["request_id"]


# --- AC-03: RequestValidationError -> 422 / INVALID_REQUEST ----------------


def test_missing_required_query_param_returns_422_invalid_request(error_client: TestClient) -> None:
    response = error_client.get("/boom/validate")  # missing required `count`

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    # Deliberately no per-field breakdown (would require echoing raw input).
    assert body["error"]["details"] == {}


def test_valid_query_param_is_not_treated_as_an_error(error_client: TestClient) -> None:
    """Boundary/positive control for the validation-error test above."""
    response = error_client.get("/boom/validate", params={"count": 3})

    assert response.status_code == 200
    assert response.json() == {"count": 3}


# --- AC-04: unhandled Exception -> 500 / INTERNAL_ERROR, no leak -----------


def test_unhandled_exception_returns_generic_500_without_leaking_exception_text(
    error_client: TestClient,
) -> None:
    response = error_client.get("/boom/unhandled")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "An internal server error occurred."
    raw_body = response.text
    assert _SECRET_EXCEPTION_TEXT not in raw_body
    assert "ValueError" not in raw_body
    assert "Traceback" not in raw_body


# --- AC-05: default StarletteHTTPException (undefined route) --------------


def test_undefined_route_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/this-route-does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "INVALID_REQUEST"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]
    assert isinstance(body["error"]["request_id"], str) and body["error"]["request_id"]


# --- AC-06: request-ID generation/propagation, success and error paths ----


def test_success_response_gets_a_generated_request_id_when_absent(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    header_value = response.headers.get(REQUEST_ID_HEADER)
    assert header_value
    # Current implementation always generates a uuid4; format-checked, not
    # over-specified as a contract (the header value is opaque by design).
    uuid.UUID(header_value)


def test_success_response_echoes_inbound_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health/live", headers={REQUEST_ID_HEADER: "corr-abc-123"})

    assert response.headers.get(REQUEST_ID_HEADER) == "corr-abc-123"


def test_error_response_request_id_matches_header_and_body(client: TestClient) -> None:
    response = client.get(
        "/api/v1/this-route-does-not-exist", headers={REQUEST_ID_HEADER: "corr-error-456"}
    )

    assert response.headers.get(REQUEST_ID_HEADER) == "corr-error-456"
    assert response.json()["error"]["request_id"] == "corr-error-456"


def test_blank_inbound_request_id_is_treated_as_absent(error_client: TestClient) -> None:
    """Boundary case: whitespace-only header must not be echoed verbatim."""
    response = error_client.get("/boom/app-error", headers={REQUEST_ID_HEADER: "   "})

    header_value = response.headers.get(REQUEST_ID_HEADER)
    assert header_value is not None
    assert header_value.strip() == header_value
    assert header_value != "   "
