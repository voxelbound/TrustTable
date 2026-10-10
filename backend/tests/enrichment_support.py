"""Test support for the persisted AI enrichment (`UX-05b`).

The explanation route never calls a model any more: an AI explanation is
requested with `POST .../ai-enrichment`, runs on a worker, and is then read
back through `GET .../explanation`. These helpers do that sequence and wait on
the *state*, never on a sleep of a guessed length.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

_DEADLINE_SECONDS = 20.0


def enrichment_url(analysis_id: str, finding_id: str) -> str:
    return f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/ai-enrichment"


def explanation_url(analysis_id: str, finding_id: str) -> str:
    return f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/explanation"


def wait_for_enrichment(client: TestClient, analysis_id: str, finding_id: str) -> dict[str, Any]:
    """Poll the status route until the enrichment is no longer `preparing`."""
    deadline = time.monotonic() + _DEADLINE_SECONDS
    while True:
        body: dict[str, Any] = client.get(enrichment_url(analysis_id, finding_id)).json()
        if body["state"] != "preparing":
            return body
        if time.monotonic() > deadline:
            raise AssertionError("the AI enrichment stayed preparing")
        time.sleep(0.01)


def request_enrichment(client: TestClient, analysis_id: str, finding_id: str) -> dict[str, Any]:
    """Start the enrichment and wait for it to finish; returns its final state."""
    started = client.post(enrichment_url(analysis_id, finding_id))
    assert started.status_code == 202, started.text
    return wait_for_enrichment(client, analysis_id, finding_id)


def get_ai_explanation(client: TestClient, analysis_id: str, finding_id: str) -> Response:
    """What the explanation route used to do in one call: request the AI
    enrichment, wait for it, then read the explanation."""
    request_enrichment(client, analysis_id, finding_id)
    response: Response = client.get(explanation_url(analysis_id, finding_id))
    return response
