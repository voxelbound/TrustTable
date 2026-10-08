"""Request-body limits enforced by the backend (`UX-02`, D-068,
`docs/api-specification.md` §15). The frontend proxy applies no size limit, so
these tests are the proof that no route is left unbounded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from trusttable_backend.config import get_settings
from trusttable_backend.main import create_app
from trusttable_backend.persistence import build_session_factory
from trusttable_backend.persistence.models import AnalysisRecord, StagedUploadRecord
from trusttable_backend.request_limits import DEFAULT_BODY_LIMIT_BYTES

_MIB = 1024 * 1024
_JSON = {"content-type": "application/json"}


@pytest.fixture
def small_limit_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MAX_FILE_SIZE_MB", "1")
    get_settings.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client


def _count(client: TestClient, model: type) -> int:
    with build_session_factory(client.app.state.analysis_engine)() as session:  # type: ignore[attr-defined]
        return int(session.scalar(select(func.count()).select_from(model)) or 0)


def test_an_oversize_json_body_is_413_with_the_shared_error_envelope(
    client: TestClient,
) -> None:
    body = b'{"staging_ref": "' + b"a" * (DEFAULT_BODY_LIMIT_BYTES + 10) + b'"}'

    response = client.post("/api/v1/staged-uploads/inspect", content=body, headers=_JSON)

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "REQUEST_TOO_LARGE"
    assert error["details"] == {"max_bytes": DEFAULT_BODY_LIMIT_BYTES}
    assert error["request_id"]
    assert response.headers["x-request-id"] == error["request_id"]
    assert response.headers["cache-control"] == "no-store"


def test_a_streamed_body_with_no_declared_length_is_still_counted(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"staging_ref": "'
        for _ in range(12):
            yield b"a" * (128 * 1024)
        yield b'"}'

    response = client.post("/api/v1/staged-uploads/discard", content=chunks(), headers=_JSON)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_a_normal_json_body_is_unaffected(client: TestClient) -> None:
    response = client.post("/api/v1/staged-uploads/discard", json={"staging_ref": "A" * 43})

    assert response.status_code == 204


@pytest.mark.parametrize("path", ["/api/v1/staged-uploads", "/api/v1/analyses"])
def test_an_upload_beyond_the_limit_is_413_and_nothing_is_created(
    small_limit_client: TestClient, path: str
) -> None:
    oversize = b"a,b\n" + b"1,2\n" * (3 * _MIB // 4)

    response = small_limit_client.post(path, files={"file": ("data.csv", oversize, "text/csv")})

    assert response.status_code == 413
    error = response.json()["error"]
    assert error["code"] == "FILE_TOO_LARGE"
    assert error["details"] == {"max_bytes": _MIB}
    assert _count(small_limit_client, StagedUploadRecord) == 0
    assert _count(small_limit_client, AnalysisRecord) == 0


@pytest.mark.parametrize("path", ["/api/v1/staged-uploads", "/api/v1/analyses"])
def test_a_streamed_upload_with_no_declared_length_is_counted_too(
    small_limit_client: TestClient, path: str
) -> None:
    boundary = "xBOUNDARYx"

    def chunks() -> Iterator[bytes]:
        yield (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="d.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode()
        for _ in range(40):
            yield b"1,2\n" * (64 * 1024 // 4)
        yield f"\r\n--{boundary}--\r\n".encode()

    response = small_limit_client.post(
        path,
        content=chunks(),
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_a_file_at_the_limit_is_not_refused_by_the_body_counter(
    small_limit_client: TestClient,
) -> None:
    exactly = b"a,b\n" + b"1,2\n" * ((_MIB - 4) // 4)
    assert len(exactly) <= _MIB

    response = small_limit_client.post(
        "/api/v1/staged-uploads", files={"file": ("d.csv", exactly, "text/csv")}
    )

    assert response.status_code == 201


def test_the_limit_follows_the_configured_maximum(
    make_limit_client: Callable[[str], TestClient],
) -> None:
    client = make_limit_client("2")
    # Just under 2 MiB, so over what a 1 MiB configuration would accept.
    two_mib_file = b"a,b\n" + b"1,2\n" * ((2 * _MIB - 4) // 4)
    assert _MIB < len(two_mib_file) <= 2 * _MIB

    response = client.post(
        "/api/v1/staged-uploads", files={"file": ("d.csv", two_mib_file, "text/csv")}
    )

    assert response.status_code == 201


@pytest.fixture
def make_limit_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], TestClient]]:
    opened: list[TestClient] = []

    def build(max_mb: str) -> TestClient:
        monkeypatch.setenv("MAX_FILE_SIZE_MB", max_mb)
        get_settings.cache_clear()
        test_client = TestClient(create_app())
        test_client.__enter__()
        opened.append(test_client)
        return test_client

    yield build
    for test_client in opened:
        test_client.__exit__(None, None, None)
