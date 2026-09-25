"""Interrupted-analysis-on-restart reconciliation (`DB-01`).

`docs/domain-model.md` §5's "active analyses interrupted by restart
become failed" invariant and `docs/decision-log.md` D-018's "interrupted
active jobs fail safely and can be retried": any analysis a restart finds
in a non-terminal state (`QUEUED`/`VALIDATING`/`PARSING`/`PROFILING`/
`DETECTING`) was not actually running (this project has no background
worker yet, `JOB-01`) — the process that would have advanced it is gone.
`reconcile_interrupted_analyses` deterministically transitions every such
analysis to `FAILED` with a fixed, safe, non-leaking failure code, the
same `AnalysisFailure` shape `analysis.service.run_analysis`'s own
exception-isolation path already uses.

`main.create_app()` is the only real caller (see its own docstring) —
this function is a plain, directly-callable unit, not a task queued
somewhere: the false positive this package's own semantic contract names
explicitly (writing this as a standalone function that real startup never
actually invokes) is avoided by `create_app()` calling it unconditionally
on every application construction, not merely under test.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from ..analysis.service import AnalysisFailure, AnalysisState
from .store import SqlAnalysisStore

INTERRUPTED_BY_RESTART_CODE = "analysis.interrupted_by_restart"
INTERRUPTED_BY_RESTART_MESSAGE = (
    "Analysis was left in a non-terminal state by an unexpected application restart"
)


def reconcile_interrupted_analyses(store: SqlAnalysisStore) -> tuple[str, ...]:
    """Transition every non-terminal persisted analysis to `FAILED`.

    Returns the `analysis_id`s actually transitioned, for test/evidence
    purposes. A `COMPLETED`/`FAILED`/`CANCELLED` analysis is never
    touched — `SqlAnalysisStore.non_terminal_analysis_ids` already
    excludes them at the query level, and this function additionally
    never calls `store.replace` for any id it did not itself select.
    """
    transitioned: list[str] = []
    for analysis_id in store.non_terminal_analysis_ids():
        analysis = store.get(analysis_id)
        if analysis is None:
            # Deleted between the id query and this read (no concurrent
            # writer exists yet in this project's single-process model,
            # but never assume it away): nothing to reconcile.
            continue
        failed_at = datetime.now(UTC)
        failed = replace(
            analysis,
            state=AnalysisState.FAILED,
            failure=AnalysisFailure(
                code=INTERRUPTED_BY_RESTART_CODE, message=INTERRUPTED_BY_RESTART_MESSAGE
            ),
            failed_at=failed_at,
        )
        store.replace(failed)
        transitioned.append(analysis_id)
    return tuple(transitioned)
