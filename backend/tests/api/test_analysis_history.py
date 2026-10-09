"""HTTP tests for history, rerun and the "analysed before" notice (`UX-03`, D-069).

The properties under test: the list is bounded, newest first and content-free;
rerun makes a new independent analysis and leaves the original untouched; the
notice is a lookup over live, completed analyses that never returns a digest and
forgets an analysis the moment it is deleted.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import trusttable_backend.analysis.service as service_module
from trusttable_backend.analysis import create_analysis
from trusttable_backend.persistence import build_session_factory
from trusttable_backend.persistence.models import AnalysisRecord

_CSV = b"id,name,amount\n1,Ada,10\n2,Grace,20\n3,Linus,30\n"
_OTHER_CSV = b"id,name,amount\n1,Ada,10\n2,Grace,20\n3,Linus,31\n"
_DIGEST = hashlib.sha256(_CSV).hexdigest()
_TERMINAL = {"completed", "failed", "cancelled"}


def _wait_terminal(client: TestClient, analysis_id: str, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state in _TERMINAL:
            return str(state)
        time.sleep(0.01)
    raise AssertionError("analysis did not finish")


def _analyse(client: TestClient, content: bytes = _CSV, filename: str = "data.csv") -> str:
    """Stage a file, run it, and wait until the analysis completes."""
    staged = client.post("/api/v1/staged-uploads", files={"file": (filename, content, "text/csv")})
    ref = staged.json()["staging_ref"]
    run = client.post("/api/v1/staged-uploads/run", json={"staging_ref": ref, "worksheet": None})
    assert run.status_code == 202
    analysis_id = str(run.json()["analysis"]["analysis_id"])
    assert _wait_terminal(client, analysis_id) == "completed"
    return analysis_id


def _stage(client: TestClient, content: bytes = _CSV, filename: str = "data.csv") -> Any:
    return client.post("/api/v1/staged-uploads", files={"file": (filename, content, "text/csv")})


def _digest_rows(client: TestClient, digest: str) -> int:
    with build_session_factory(client.app.state.analysis_engine)() as session:  # type: ignore[attr-defined]
        return int(
            session.scalar(
                select(func.count())
                .select_from(AnalysisRecord)
                .where(AnalysisRecord.content_sha256 == digest)
            )
            or 0
        )


# --- the list ---------------------------------------------------------------


def test_history_is_empty_before_any_analysis(client: TestClient) -> None:
    body = client.get("/api/v1/analyses").json()
    assert body == {"items": [], "limit": 20}


def test_history_lists_newest_first_with_content_free_fields(client: TestClient) -> None:
    first = _analyse(client, _CSV, "first.csv")
    second = _analyse(client, _OTHER_CSV, "second.csv")

    response = client.get("/api/v1/analyses")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["analysis_id"] for item in items] == [second, first]
    item = items[0]
    assert item["original_filename"] == "second.csv"
    assert item["state"] == "completed"
    assert item["format"] == "csv"
    assert item["source"] == "upload"
    assert item["byte_size"] == len(_OTHER_CSV)
    assert item["trust_label"] is not None
    assert set(item) == {
        "analysis_id",
        "state",
        "original_filename",
        "format",
        "byte_size",
        "selected_worksheet",
        "source",
        "created_at",
        "completed_at",
        "trust_label",
        "finding_count",
    }


def test_history_never_carries_a_digest_or_a_cell_value(client: TestClient) -> None:
    _analyse(client)
    text = client.get("/api/v1/analyses").text
    assert _DIGEST not in text
    assert "content_hash" not in text
    assert "sha256" not in text.lower()
    assert "Grace" not in text


def test_history_marks_the_bundled_demo(client: TestClient) -> None:
    created = client.post("/api/v1/demo/sales")
    assert _wait_terminal(client, created.json()["analysis"]["analysis_id"]) == "completed"
    assert client.get("/api/v1/analyses").json()["items"][0]["source"] == "demo"


def test_history_limit_is_bounded(client: TestClient) -> None:
    for name in ("a.csv", "b.csv", "c.csv"):
        _analyse(client, _CSV, name)
    assert len(client.get("/api/v1/analyses", params={"limit": 2}).json()["items"]) == 2
    assert client.get("/api/v1/analyses", params={"limit": 0}).status_code == 422
    assert client.get("/api/v1/analyses", params={"limit": 51}).status_code == 422
    assert client.get("/api/v1/analyses", params={"limit": 50}).status_code == 200


def test_a_deleted_analysis_leaves_the_list(client: TestClient) -> None:
    analysis_id = _analyse(client)
    assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 204
    assert client.get("/api/v1/analyses").json()["items"] == []


# --- rerun ------------------------------------------------------------------


def test_rerun_makes_a_new_independent_analysis_and_leaves_the_original(
    client: TestClient,
) -> None:
    original = _analyse(client)
    before = client.get(f"/api/v1/analyses/{original}").json()

    response = client.post(f"/api/v1/analyses/{original}/rerun")

    assert response.status_code == 202
    body = response.json()
    new_id = body["analysis"]["analysis_id"]
    assert new_id != original
    assert body["analysis"]["state"] == "queued"
    assert body["status_url"] == f"/api/v1/analyses/{new_id}/status"
    assert _wait_terminal(client, new_id) == "completed"
    assert client.get(f"/api/v1/analyses/{original}").json() == before
    # No lineage is recorded: a rerun is not a retry.
    assert client.get(f"/api/v1/analyses/{new_id}").json()["retry_source_analysis_id"] is None


def test_rerun_copies_no_review_state_and_survives_deleting_the_original(
    client: TestClient,
) -> None:
    original = client.post("/api/v1/demo/sales").json()["analysis"]["analysis_id"]
    assert _wait_terminal(client, original) == "completed"
    finding_id = client.get(f"/api/v1/analyses/{original}/findings").json()["items"][0][
        "finding_id"
    ]
    reviewed = client.put(
        f"/api/v1/analyses/{original}/findings/{finding_id}/review",
        json={"state": "confirmed", "note": "kept", "dismissal_reason": None},
    )
    assert reviewed.status_code == 200

    new_id = client.post(f"/api/v1/analyses/{original}/rerun").json()["analysis"]["analysis_id"]
    assert _wait_terminal(client, new_id) == "completed"
    assert client.delete(f"/api/v1/analyses/{original}").status_code == 204

    findings = client.get(f"/api/v1/analyses/{new_id}/findings").json()["items"]
    assert findings
    assert all(f["review_state"] == "unreviewed" for f in findings)


def test_a_failed_analysis_can_be_rerun_too(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic pipeline failure")

    monkeypatch.setattr(service_module, "parse_csv", _boom)
    created = client.post("/api/v1/demo/sales").json()["analysis"]["analysis_id"]
    assert _wait_terminal(client, created) == "failed"
    monkeypatch.undo()

    response = client.post(f"/api/v1/analyses/{created}/rerun")

    assert response.status_code == 202
    assert _wait_terminal(client, response.json()["analysis"]["analysis_id"]) == "completed"


def test_rerun_of_an_unfinished_analysis_is_refused(client: TestClient) -> None:
    # Created but never submitted to the pool, so it stays queued.
    queued = create_analysis(client.app.state.analysis_store)  # type: ignore[attr-defined]

    response = client.post(f"/api/v1/analyses/{queued.analysis_id}/rerun")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_RERUNNABLE"


def test_rerun_of_an_unknown_analysis_is_not_found(client: TestClient) -> None:
    response = client.post("/api/v1/analyses/does-not-exist/rerun")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


# --- the "analysed before" notice ----------------------------------------------


def test_a_file_never_analysed_has_no_notice(client: TestClient) -> None:
    assert _stage(client).json()["previously_analysed"] is None


def test_the_same_bytes_are_recognised_without_exposing_a_digest(client: TestClient) -> None:
    analysis_id = _analyse(client, _CSV, "sales.csv")

    staged = _stage(client, _CSV, "renamed.csv")

    notice = staged.json()["previously_analysed"]
    assert notice["kind"] == "same_file"
    assert notice["count"] == 1
    assert notice["latest_analysis_id"] == analysis_id
    assert notice["latest_filename"] == "sales.csv"
    assert _DIGEST not in staged.text
    assert "content_hash" not in staged.text


def test_the_notice_also_appears_when_a_staged_file_is_inspected_again(
    client: TestClient,
) -> None:
    _analyse(client)
    ref = _stage(client).json()["staging_ref"]

    inspected = client.post(
        "/api/v1/staged-uploads/inspect", json={"staging_ref": ref, "worksheet": None}
    )

    assert inspected.json()["previously_analysed"]["kind"] == "same_file"


def test_a_same_name_file_with_different_bytes_gets_only_a_name_hint(
    client: TestClient,
) -> None:
    _analyse(client, _CSV, "sales.csv")

    notice = _stage(client, _OTHER_CSV, "SALES.csv").json()["previously_analysed"]

    assert notice["kind"] == "same_name"
    assert notice["count"] == 1


def test_a_different_name_and_different_bytes_get_no_notice(client: TestClient) -> None:
    _analyse(client, _CSV, "sales.csv")
    assert _stage(client, _OTHER_CSV, "other.csv").json()["previously_analysed"] is None


def test_deleting_an_analysis_makes_the_lookup_forget_it(client: TestClient) -> None:
    analysis_id = _analyse(client, _CSV, "sales.csv")
    assert _stage(client, _CSV, "sales.csv").json()["previously_analysed"] is not None
    assert _digest_rows(client, _DIGEST) == 1

    assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 204

    # Neither the exact-bytes match nor the name hint survives deletion, and no
    # row anywhere still holds the digest.
    assert _stage(client, _CSV, "sales.csv").json()["previously_analysed"] is None
    assert _digest_rows(client, _DIGEST) == 0


def test_only_the_remaining_analysis_is_reported_after_one_of_two_is_deleted(
    client: TestClient,
) -> None:
    first = _analyse(client, _CSV, "one.csv")
    second = _analyse(client, _CSV, "two.csv")
    assert _stage(client).json()["previously_analysed"]["count"] == 2

    client.delete(f"/api/v1/analyses/{second}")

    notice = _stage(client).json()["previously_analysed"]
    assert notice["count"] == 1
    assert notice["latest_analysis_id"] == first


def test_a_failed_analysis_does_not_count_as_analysed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic pipeline failure")

    monkeypatch.setattr(service_module, "parse_csv", _boom)
    staged = _stage(client).json()["staging_ref"]
    run = client.post("/api/v1/staged-uploads/run", json={"staging_ref": staged, "worksheet": None})
    assert _wait_terminal(client, run.json()["analysis"]["analysis_id"]) == "failed"
    monkeypatch.undo()

    assert _stage(client).json()["previously_analysed"] is None


def test_a_rerun_counts_once_it_has_completed(client: TestClient) -> None:
    original = _analyse(client)
    new_id = client.post(f"/api/v1/analyses/{original}/rerun").json()["analysis"]["analysis_id"]
    assert _wait_terminal(client, new_id) == "completed"

    assert _stage(client).json()["previously_analysed"]["count"] == 2


def test_an_unreadable_file_gets_no_notice_and_stores_nothing(client: TestClient) -> None:
    _analyse(client)
    response = _stage(client, b"\xff\xfe\x00bad", "sales.csv")
    assert response.json()["staging_ref"] is None
    assert response.json()["previously_analysed"] is None


def test_the_openapi_contract_lists_the_new_routes_without_a_digest_field(
    client: TestClient,
) -> None:
    spec = client.get("/openapi.json").json()
    assert "get" in spec["paths"]["/api/v1/analyses"]
    assert "post" in spec["paths"]["/api/v1/analyses/{analysis_id}/rerun"]
    for name in ("AnalysisHistoryItem", "PreviousAnalysisNoticeResponse"):
        properties = spec["components"]["schemas"][name]["properties"]
        assert not any("hash" in key or "sha" in key or "digest" in key for key in properties)
