"""Tests for `JobPool` (`JOB-01`, `WP-075` AC-01/AC-03/AC-04/AC-06).

Uses the in-memory `AnalysisStore` directly (no database dependency for
these pure pool-mechanics tests — the real `SqlAnalysisStore`'s own
cross-thread safety is `DB-01`'s concern and is exercised end-to-end
against the real HTTP app in `test_analyses_async.py`). Concurrency/
cancellation control uses a monkeypatched `analysis.service.parse_csv`
as a controllable blocking gate — the same seam `run_analysis` itself
calls, so no product code changes for testability.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

import trusttable_backend.analysis.service as service_module
from trusttable_backend.analysis.service import AnalysisState, AnalysisStore, create_analysis
from trusttable_backend.jobs.pool import JobPool
from trusttable_backend.parsers.csv_parser import parse_csv as real_parse_csv

_TIMEOUT = 5.0


def _wait_until(predicate: Callable[[], bool], *, timeout: float = _TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


def test_submit_runs_analysis_to_completion_on_a_background_thread() -> None:
    store = AnalysisStore()
    pool = JobPool(store, max_workers=2)
    analysis = create_analysis(store)

    future = pool.submit(analysis.analysis_id)
    future.result(timeout=_TIMEOUT)

    completed = store.get(analysis.analysis_id)
    assert completed is not None
    assert completed.state is AnalysisState.COMPLETED
    pool.shutdown()


def test_shutdown_prevents_further_submission() -> None:
    """AC-06: no worker thread outlives a shut-down pool — proven
    black-box via the standard `ThreadPoolExecutor` post-shutdown
    contract rather than inspecting private executor state.
    """
    store = AnalysisStore()
    pool = JobPool(store, max_workers=1)

    pool.shutdown(wait=True)

    with pytest.raises(RuntimeError):
        pool.submit("does-not-matter")


def test_request_cancel_before_pickup_cancels_without_running_the_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancellation requested while an analysis is still queued behind
    a busy sole worker takes effect at `run_analysis`'s very first
    checkpoint — the target analysis never reaches `parsing`.
    """
    store = AnalysisStore()
    pool = JobPool(store, max_workers=1)
    blocker = create_analysis(store)
    target = create_analysis(store)

    release = threading.Event()
    first_call_seen = threading.Event()

    def _blocking_parse_csv(content: bytes):  # type: ignore[no-untyped-def]
        first_call_seen.set()
        release.wait(timeout=_TIMEOUT)
        return real_parse_csv(content)

    monkeypatch.setattr(service_module, "parse_csv", _blocking_parse_csv)

    pool.submit(blocker.analysis_id)
    _wait_until(first_call_seen.is_set)

    target_future = pool.submit(target.analysis_id)
    # The sole worker is occupied by `blocker`; `target` is still queued.
    still_queued = store.get(target.analysis_id)
    assert still_queued is not None
    assert still_queued.state is AnalysisState.QUEUED

    pool.request_cancel(target.analysis_id)
    release.set()
    target_future.result(timeout=_TIMEOUT)

    cancelled = store.get(target.analysis_id)
    assert cancelled is not None
    assert cancelled.state is AnalysisState.CANCELLED
    assert cancelled.cancelled_at is not None

    pool.shutdown()


def test_request_cancel_while_running_stops_before_the_next_stage_sibling_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-04 (decisive cancellation proof): an analysis cancelled while
    genuinely in flight (confirmed `parsing`, mid-`parse_csv`) reaches
    `cancelled`, never `completed`; a sibling submitted without a
    cancellation request on the same pool completes normally.
    """
    store = AnalysisStore()
    pool = JobPool(store, max_workers=2)
    target = create_analysis(store)
    sibling = create_analysis(store)

    entered = threading.Event()
    release = threading.Event()

    def _blocking_parse_csv(content: bytes):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(timeout=_TIMEOUT)
        return real_parse_csv(content)

    monkeypatch.setattr(service_module, "parse_csv", _blocking_parse_csv)

    target_future = pool.submit(target.analysis_id)
    _wait_until(entered.is_set)

    in_flight = store.get(target.analysis_id)
    assert in_flight is not None
    assert in_flight.state is AnalysisState.PARSING  # confirmed still non-terminal

    pool.request_cancel(target.analysis_id)
    release.set()
    target_future.result(timeout=_TIMEOUT)

    cancelled = store.get(target.analysis_id)
    assert cancelled is not None
    assert cancelled.state is AnalysisState.CANCELLED
    assert cancelled.cancelled_at is not None

    sibling_future = pool.submit(sibling.analysis_id)
    sibling_future.result(timeout=_TIMEOUT)
    completed_sibling = store.get(sibling.analysis_id)
    assert completed_sibling is not None
    assert completed_sibling.state is AnalysisState.COMPLETED

    pool.shutdown()


def test_at_most_max_workers_run_concurrently(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-03: submitting more analyses than `max_workers` never lets more
    than `max_workers` run truly concurrently; the rest queue.
    """
    max_workers = 2
    store = AnalysisStore()
    pool = JobPool(store, max_workers=max_workers)
    analyses = [create_analysis(store) for _ in range(max_workers + 2)]

    active = 0
    peak = 0
    lock = threading.Lock()
    release = threading.Event()

    def _blocking_parse_csv(content: bytes):  # type: ignore[no-untyped-def]
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        release.wait(timeout=_TIMEOUT)
        with lock:
            active -= 1
        return real_parse_csv(content)

    monkeypatch.setattr(service_module, "parse_csv", _blocking_parse_csv)

    futures = [pool.submit(analysis.analysis_id) for analysis in analyses]
    _wait_until(lambda: peak == max_workers)
    time.sleep(0.05)  # let any over-scheduled worker start, if the bound were broken
    assert peak == max_workers

    release.set()
    for future in futures:
        future.result(timeout=_TIMEOUT)

    for analysis in analyses:
        completed = store.get(analysis.analysis_id)
        assert completed is not None
        assert completed.state is AnalysisState.COMPLETED

    pool.shutdown()
