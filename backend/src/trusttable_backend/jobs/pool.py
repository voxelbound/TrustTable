"""`JobPool`: a bounded in-process worker pool (`JOB-01`, `WP-075`,
`docs/architecture.md` §9, `ADR-004`).

A thin wrapper around `concurrent.futures.ThreadPoolExecutor`, sized
from `Settings.background_worker_count` (`FND-02`). `submit` runs
`analysis.service.run_analysis` on a background thread instead of
inside the HTTP request that created the analysis — the decisive change
this package makes to `main.create_app()`'s real production wiring (see
this module's own false-positive disclosure below).

Cancellation is cooperative, never a direct store write from this class:
`request_cancel` only ever sets an in-memory, process-local flag for one
`analysis_id`. The *only* writer of the eventual `CANCELLED` state is
`run_analysis` itself, running on the worker thread that owns that
row — this is what prevents a race between a route handler's own store
write and the worker's own concurrent read-modify-write of the same
`Analysis` (the false positive `docs/architecture.md` §9's "cancellation
flag" wording exists specifically to avoid).

Process-local by design (`ADR-004`: "one application instance"): a
process restart already loses every in-memory cancellation flag, but
also already fails every non-terminal analysis via `persistence.
reconcile_interrupted_analyses` (`DB-01`) before this pool ever accepts
new work — so a lost flag can never silently resurrect as "still
running, cancellation forgotten."
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from functools import partial

from ..analysis.service import AnalysisStoreProtocol, run_analysis


class JobPool:
    """Runs `run_analysis` on a bounded background thread pool."""

    def __init__(self, store: AnalysisStoreProtocol, max_workers: int) -> None:
        self._store = store
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="analysis-worker"
        )
        self._cancel_requested: set[str] = set()
        self._lock = threading.Lock()

    def submit(self, analysis_id: str) -> Future[None]:
        """Run `run_analysis(store, analysis_id)` on a background thread.

        Returns the underlying `Future` — production callers do not need
        it (the real result lives in the store, observed via `GET
        /status`/`GET /analyses/{id}`), but tests use it to wait for
        completion deterministically instead of polling.
        """
        return self._executor.submit(self._run, analysis_id)

    def request_cancel(self, analysis_id: str) -> None:
        """Request cooperative cancellation for `analysis_id`.

        Effective the next time `run_analysis`'s own `cancel_check`
        callback is consulted (before it starts, if not yet picked up by
        a worker; at the next stage checkpoint, if already running). A
        no-op, not an error, for an unknown or already-terminal
        `analysis_id` — `run_analysis` itself only ever checks this flag
        while an analysis remains non-terminal.
        """
        with self._lock:
            self._cancel_requested.add(analysis_id)

    def shutdown(self, *, wait: bool = True) -> None:
        """Shut down the pool. `wait=True` (the default, used at real
        application shutdown) lets in-flight work finish cleanly rather
        than abandoning a partial store write mid-stage.
        """
        self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def _cancel_check(self, analysis_id: str) -> bool:
        with self._lock:
            return analysis_id in self._cancel_requested

    def _run(self, analysis_id: str) -> None:
        try:
            run_analysis(
                self._store, analysis_id, cancel_check=partial(self._cancel_check, analysis_id)
            )
        finally:
            with self._lock:
                self._cancel_requested.discard(analysis_id)
