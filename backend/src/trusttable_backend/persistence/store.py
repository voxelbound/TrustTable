"""`SqlAnalysisStore` (`DB-01`): a durable `Analysis` store backed by
`models.AnalysisRecord`, structurally satisfying the exact
`add(analysis)`/`get(analysis_id)`/`replace(analysis)` interface
`analysis.service`'s functions already call through
`AnalysisStoreProtocol`.

Each method opens one short-lived `Session` (`database.build_session_factory`)
rather than holding a connection open for the store's lifetime — this
project's single-process, single-worker deployment model (`ADR-003`)
makes this safe and keeps `main.create_app()`'s per-request behavior
unsurprising. `add`/`replace` both upsert (matching
`analysis.service.AnalysisStore`'s own in-memory dict-assignment
semantics, where both already overwrite unconditionally) rather than
distinguishing insert-only from update-only.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..analysis.service import Analysis, AnalysisState
from . import serializers
from .database import build_session_factory
from .models import AnalysisRecord

#: `AnalysisState` values `Analysis.__post_init__` never leaves pending
#: further pipeline work — used by `reconciliation.py` to find every
#: analysis a restart interrupted. Kept here, next to the schema/row
#: shape it queries, rather than duplicated in `reconciliation.py`.
TERMINAL_STATES = frozenset(
    {AnalysisState.COMPLETED.value, AnalysisState.FAILED.value, AnalysisState.CANCELLED.value}
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _from_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _analysis_to_row_values(analysis: Analysis) -> dict[str, object]:
    return {
        "analysis_id": analysis.analysis_id,
        "state": analysis.state.value,
        "created_at": _iso(analysis.created_at),
        "started_at": _iso(analysis.started_at),
        "completed_at": _iso(analysis.completed_at),
        "failed_at": _iso(analysis.failed_at),
        "cancelled_at": _iso(analysis.cancelled_at),
        "content": analysis.content,
        "dataset_json": serializers.encode(analysis.dataset),
        "security_exposure_json": serializers.encode(analysis.security_exposure),
        "dataset_profile_json": serializers.encode(analysis.dataset_profile),
        "findings_json": serializers.encode(analysis.findings),
        "priority_scores_json": serializers.encode(analysis.priority_scores),
        "evidence_json": serializers.encode(analysis.evidence),
        "trust_assessment_json": serializers.encode(analysis.trust_assessment),
        "failure_json": serializers.encode(analysis.failure),
        "context_json": serializers.encode(analysis.context),
        "guided_questions_json": serializers.encode(analysis.guided_questions),
        "context_version": analysis.context_version,
        "context_finalized": analysis.context_finalized,
    }


def _row_to_analysis(row: AnalysisRecord) -> Analysis:
    return Analysis(
        analysis_id=row.analysis_id,
        dataset=serializers.decode(row.dataset_json),
        content=row.content,
        state=AnalysisState(row.state),
        security_exposure=serializers.decode(row.security_exposure_json),
        dataset_profile=serializers.decode(row.dataset_profile_json)
        if row.dataset_profile_json is not None
        else None,
        findings=serializers.decode(row.findings_json),
        priority_scores=serializers.decode(row.priority_scores_json),
        evidence=serializers.decode(row.evidence_json),
        trust_assessment=serializers.decode(row.trust_assessment_json)
        if row.trust_assessment_json is not None
        else None,
        failure=serializers.decode(row.failure_json) if row.failure_json is not None else None,
        created_at=datetime.fromisoformat(row.created_at),
        started_at=_from_iso(row.started_at),
        completed_at=_from_iso(row.completed_at),
        failed_at=_from_iso(row.failed_at),
        cancelled_at=_from_iso(row.cancelled_at),
        context=serializers.decode(row.context_json) if row.context_json is not None else None,
        guided_questions=serializers.decode(row.guided_questions_json),
        context_version=row.context_version,
        context_finalized=row.context_finalized,
    )


class SqlAnalysisStore:
    """A durable `Analysis` store backed by SQLAlchemy 2 + SQLite."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = build_session_factory(engine)

    def add(self, analysis: Analysis) -> None:
        self._upsert(analysis)

    def replace(self, analysis: Analysis) -> None:
        self._upsert(analysis)

    def _upsert(self, analysis: Analysis) -> None:
        values = _analysis_to_row_values(analysis)
        with self._session_factory() as session:
            existing = session.get(AnalysisRecord, analysis.analysis_id)
            if existing is None:
                session.add(AnalysisRecord(**values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
            session.commit()

    def get(self, analysis_id: str) -> Analysis | None:
        """Return the persisted `Analysis`, or `None` if unknown.

        Raises whatever `Analysis.__post_init__`/a nested dataclass's own
        `__post_init__` raises for a persisted row that no longer
        satisfies its invariants (AC-03) — reconstruction always calls
        each dataclass's real constructor (`serializers.decode`); this
        method performs no separate validation of its own.
        """
        with self._session_factory() as session:
            row = session.get(AnalysisRecord, analysis_id)
            if row is None:
                return None
            return _row_to_analysis(row)

    def non_terminal_analysis_ids(self) -> tuple[str, ...]:
        """Return every persisted `analysis_id` left in a non-terminal
        state — used only by `reconciliation.reconcile_interrupted_analyses`,
        not part of the `AnalysisStoreProtocol` surface `analysis.service`
        itself calls.
        """
        with self._session_factory() as session:
            stmt = select(AnalysisRecord.analysis_id).where(
                AnalysisRecord.state.notin_(TERMINAL_STATES)
            )
            return tuple(session.scalars(stmt).all())
