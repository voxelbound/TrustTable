"""The v0.3 promise as one ordered workflow (`REL-03`).

One uploaded CSV is taken through the whole persisted manager workflow against
the real HTTP application and one on-disk SQLite database: analysis, findings,
a finding review, a rule that is created and run, the rules export, a stored
Markdown report, a restart (a second, independently constructed application on
the same database), and finally permanent deletion.

Every step asserts content, not just a status code, and the later steps depend
on the earlier ones (the report is generated after the review and the rule, so
it must reflect them; the restart must return exactly what was stored; deletion
must remove what the restart proved was there). This is the release-level
composition of behavior each `v0.3` package already proves in isolation.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from trusttable_backend.main import create_app

_TERMINAL = {"completed", "failed", "cancelled"}
_DEMO_CSV = Path(__file__).resolve().parents[3] / "demo-data" / "sales_demo.csv"
_NOTE = "Confirmed with the sales operations lead."


def _wait_completed(client: TestClient, analysis_id: str) -> None:
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state in _TERMINAL:
            assert state == "completed"
            return
        time.sleep(0.01)
    raise AssertionError(f"analysis {analysis_id} did not finish")


def _read_everything(client: TestClient, analysis_id: str, report_id: str) -> dict[str, Any]:
    base = f"/api/v1/analyses/{analysis_id}"
    first_finding = client.get(f"{base}/findings/0")
    assert first_finding.status_code == 200
    rules = client.get(f"{base}/rules")
    assert rules.status_code == 200
    download = client.get(f"{base}/reports/{report_id}/download")
    assert download.status_code == 200
    return {
        "analysis": client.get(base).json(),
        "profile": client.get(f"{base}/profile").json(),
        "findings": client.get(f"{base}/findings").json(),
        "finding_zero": first_finding.json(),
        "rules": rules.json(),
        "rules_json": client.get(f"{base}/exports/rules.json").content,
        "report_metadata": client.get(f"{base}/reports/{report_id}").json(),
        "report_bytes": download.content,
    }


def test_complete_persisted_csv_workflow_across_a_restart_and_deletion() -> None:
    csv_bytes = _DEMO_CSV.read_bytes()

    with TestClient(create_app()) as first:
        # 1. Upload a CSV and let the background analysis finish.
        created = first.post(
            "/api/v1/analyses", files={"file": ("sales_demo.csv", csv_bytes, "text/csv")}
        )
        assert created.status_code == 202
        analysis_id: str = created.json()["analysis"]["analysis_id"]
        _wait_completed(first, analysis_id)
        base = f"/api/v1/analyses/{analysis_id}"

        # 2. Deterministic findings exist and start unreviewed.
        findings = first.get(f"{base}/findings").json()
        assert findings["total_items"] > 0
        item = findings["items"][0]
        assert item["review_state"] == "unreviewed"

        # 3. Review one finding; the saved state is returned and shown in the list.
        reviewed = first.put(
            f"{base}/findings/{item['finding_id']}/review",
            json={"state": "confirmed", "note": _NOTE},
        )
        assert reviewed.status_code == 200
        assert reviewed.json()["review_state"] == "confirmed"
        assert reviewed.json()["note"] == _NOTE
        assert reviewed.json()["reviewed_at"] is not None
        relisted = first.get(f"{base}/findings").json()["items"]
        assert relisted[0]["review_state"] == "confirmed"
        assert all(other["review_state"] == "unreviewed" for other in relisted[1:])

        # 4. Create a rule; it is executed and its counts are real.
        rule_response = first.post(
            f"{base}/rules",
            json={
                "name": "quantity is present",
                "description": "Every order line has a quantity.",
                "severity": "medium",
                "column_names": ["quantity"],
                "rule_type": "not_null",
            },
        )
        assert rule_response.status_code == 201
        rule = rule_response.json()
        result = rule["last_result"]
        assert result["error"] is None
        assert result["pass_count"] + result["fail_count"] + result["skipped_count"] > 0

        # 5. The rules export contains exactly that validated rule.
        exported = json.loads(first.get(f"{base}/exports/rules.json").text)
        assert exported["analysis_id"] == analysis_id
        assert exported["rule_count"] == 1
        assert [entry["rule_id"] for entry in exported["rules"]] == [rule["rule_id"]]

        # 6. A Markdown report is stored, and its bytes match the recorded hash.
        report = first.post(f"{base}/reports", json={"options": {}})
        assert report.status_code == 201
        report_id: str = report.json()["report_id"]
        markdown = first.get(f"{base}/reports/{report_id}/download")
        assert markdown.status_code == 200
        assert hashlib.sha256(markdown.content).hexdigest() == report.json()["content_sha256"]
        # Markdown output escapes underscores in the file name.
        assert "sales\\_demo.csv" in markdown.text
        assert "quantity is present" in markdown.text

        before_restart = _read_everything(first, analysis_id, report_id)

    # 7. Restart: a second application on the same database returns identical data.
    with TestClient(create_app()) as second:
        after_restart = _read_everything(second, analysis_id, report_id)
        assert after_restart == before_restart
        assert after_restart["finding_zero"]["review_state"] == "confirmed"
        assert after_restart["report_bytes"] == before_restart["report_bytes"]

        # 8. Deletion is permanent and reaches every part of the workflow.
        deleted = second.delete(base)
        assert deleted.status_code == 204
        for path in (
            base,
            f"{base}/findings",
            f"{base}/rules",
            f"{base}/exports/rules.json",
            f"{base}/reports",
            f"{base}/reports/{report_id}",
            f"{base}/reports/{report_id}/download",
        ):
            gone = second.get(path)
            assert gone.status_code == 404, (path, gone.status_code)
            assert gone.json()["error"]["code"] == "ANALYSIS_NOT_FOUND", path
        assert second.delete(base).status_code == 404

    # 9. Deletion also holds after another restart.
    with TestClient(create_app()) as third:
        assert third.get(base).status_code == 404
        assert third.get(f"{base}/reports/{report_id}/download").status_code == 404
