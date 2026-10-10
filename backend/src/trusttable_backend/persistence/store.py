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

import hashlib
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm.exc import StaleDataError

from ..analysis.service import Analysis, AnalysisState, AnalysisSummary
from ..domain.ai_enrichment import AiEnrichmentRecord
from . import serializers
from .database import build_session_factory
from .models import (
    AnalysisRecord,
    ConfirmedRelationshipVersionRecord,
    FindingEnrichmentRecord,
    ReportRecord,
)

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
        "rules_json": serializers.encode(analysis.rules),
        "finding_reviews_json": serializers.encode(analysis.finding_reviews),
        "ai_enrichment_json": serializers.encode(analysis.ai_enrichment),
        "observations_json": serializers.encode(analysis.observations),
        "context_version": analysis.context_version,
        "context_finalized": analysis.context_finalized,
        "retry_source_analysis_id": analysis.retry_source_analysis_id,
    }


def _content_digest(analysis: Analysis) -> str:
    """The lookup key for "this exact file was analysed before" (`UX-03`,
    D-069): a digest of the very bytes stored beside it, never the dataset's
    own independently written `content_hash` field. Computed only when a row is
    first written, because an analysis's content never changes afterwards."""
    return hashlib.sha256(analysis.content).hexdigest()


def _row_to_summary(row: Any) -> AnalysisSummary:
    """A content-free summary from a row loaded without its large columns."""
    dataset = serializers.decode(row.dataset_json)
    assessment = (
        serializers.decode(row.trust_assessment_json)
        if row.trust_assessment_json is not None
        else None
    )
    return AnalysisSummary(
        analysis_id=row.analysis_id,
        state=AnalysisState(row.state),
        original_filename=dataset.original_filename,
        dataset_format=dataset.format,
        byte_size=dataset.byte_size,
        selected_worksheet=dataset.selected_worksheet,
        source_type=dataset.source_type,
        created_at=datetime.fromisoformat(row.created_at),
        completed_at=_from_iso(row.completed_at),
        trust_label=assessment.label.value if assessment is not None else None,
        finding_count=assessment.finding_count if assessment is not None else None,
    )


#: The columns a summary needs. Selecting these (and not `content` or the large
#: JSON columns) keeps the list and the lookup cheap and keeps raw bytes out of
#: memory.
_SUMMARY_COLUMNS = (
    AnalysisRecord.analysis_id,
    AnalysisRecord.state,
    AnalysisRecord.created_at,
    AnalysisRecord.completed_at,
    AnalysisRecord.dataset_json,
    AnalysisRecord.trust_assessment_json,
)


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
        rules=serializers.decode(row.rules_json) if row.rules_json is not None else (),
        finding_reviews=serializers.decode(row.finding_reviews_json)
        if row.finding_reviews_json is not None
        else {},
        # NULL is *not recorded*, never a zero record (`EXP-01` slice 4).
        ai_enrichment=serializers.decode(row.ai_enrichment_json)
        if row.ai_enrichment_json is not None
        else None,
        # NULL (a row written before the column existed) reads as no observations.
        observations=serializers.decode(row.observations_json)
        if row.observations_json is not None
        else (),
        context_version=row.context_version,
        context_finalized=row.context_finalized,
        retry_source_analysis_id=row.retry_source_analysis_id,
    )


#: Columns owned by a dedicated atomic operation. A whole-analysis write to
#: an existing row never sets them, so a stale copy of an `Analysis` cannot
#: revert them (`EXP-01` slice 4: `ai_enrichment_json`).
_SEPARATELY_OWNED_COLUMNS = frozenset({"ai_enrichment_json"})


class SqlAnalysisStore:
    """A durable `Analysis` store backed by SQLAlchemy 2 + SQLite.

    `ai_enrichment_json` is written when a row is first added and after
    that only by `update_ai_enrichment`; `replace` leaves it as stored, so
    a concurrent writer holding a stale `Analysis` cannot drop a recorded
    AI enrichment call.
    """

    def __init__(self, engine: Engine) -> None:
        self._session_factory = build_session_factory(engine)
        self._enrichment_lock = threading.Lock()

    def add(self, analysis: Analysis) -> None:
        values = _analysis_to_row_values(analysis)
        with self._session_factory() as session:
            existing = session.get(AnalysisRecord, analysis.analysis_id)
            if existing is None:
                session.add(AnalysisRecord(**values, content_sha256=_content_digest(analysis)))
            else:
                self._apply(existing, values)
                if existing.content_sha256 is None:
                    existing.content_sha256 = _content_digest(analysis)
            session.commit()

    def replace(self, analysis: Analysis) -> None:
        """Update an existing analysis. Never inserts: a write for an
        analysis that no longer exists (a worker finishing after the
        analysis was deleted, `DEL-01`) is dropped, so a deleted analysis
        cannot be brought back by a late write."""
        values = _analysis_to_row_values(analysis)
        with self._session_factory() as session:
            existing = session.get(AnalysisRecord, analysis.analysis_id)
            if existing is None:
                return
            self._apply(existing, values)
            try:
                session.commit()
            except StaleDataError:
                # Deleted between the read and the write.
                session.rollback()

    @staticmethod
    def _apply(existing: AnalysisRecord, values: dict[str, object]) -> None:
        for key, value in values.items():
            if key not in _SEPARATELY_OWNED_COLUMNS:
                setattr(existing, key, value)

    def delete(self, analysis_id: str) -> bool:
        """Remove the analysis, all of its reports, all of its confirmed
        relationship versions and all of its saved AI enrichments in one
        transaction (`DEL-01`, `DET-03`, `UX-05b`). Returns whether the
        analysis existed; every deletion commits or none does."""
        with self._session_factory() as session:
            session.execute(delete(ReportRecord).where(ReportRecord.analysis_id == analysis_id))
            session.execute(
                delete(FindingEnrichmentRecord).where(
                    FindingEnrichmentRecord.analysis_id == analysis_id
                )
            )
            session.execute(
                delete(ConfirmedRelationshipVersionRecord).where(
                    ConfirmedRelationshipVersionRecord.analysis_id == analysis_id
                )
            )
            result = session.execute(
                delete(AnalysisRecord).where(AnalysisRecord.analysis_id == analysis_id)
            )
            session.commit()
            return bool(result.rowcount)  # type: ignore[attr-defined]

    def update_ai_enrichment(
        self,
        analysis_id: str,
        update: Callable[[AiEnrichmentRecord | None], AiEnrichmentRecord | None],
    ) -> None:
        """Atomically read, transform and write only the AI enrichment
        column. An unknown analysis is ignored. Serialized so concurrent
        recordings cannot lose a count; no whole-analysis write can touch
        this column, so none can revert it."""
        with self._enrichment_lock, self._session_factory() as session:
            row = session.get(AnalysisRecord, analysis_id)
            if row is None:
                return
            current = (
                serializers.decode(row.ai_enrichment_json)
                if row.ai_enrichment_json is not None
                else None
            )
            row.ai_enrichment_json = serializers.encode(update(current))
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

    def list_recent(self, limit: int) -> tuple[AnalysisSummary, ...]:
        """At most `limit` analyses, newest first, as content-free summaries
        (`UX-03`, D-069). Reads only the summary columns, ordered by the
        indexed `created_at`, so it never loads stored bytes."""
        if limit <= 0:
            return ()
        with self._session_factory() as session:
            stmt = (
                select(*_SUMMARY_COLUMNS)
                .order_by(AnalysisRecord.created_at.desc(), AnalysisRecord.analysis_id)
                .limit(limit)
            )
            return tuple(_row_to_summary(row) for row in session.execute(stmt))

    def find_completed_by_content_hash(
        self, content_sha256: str, limit: int
    ) -> tuple[AnalysisSummary, ...]:
        """At most `limit` `COMPLETED` analyses whose stored bytes have this
        SHA-256, newest first, through the indexed `content_sha256` column.
        A lookup over live rows only (`UX-03`, D-069): a deleted analysis is
        gone with its row, and nothing else remembers the digest."""
        if limit <= 0:
            return ()
        with self._session_factory() as session:
            stmt = (
                select(*_SUMMARY_COLUMNS)
                .where(
                    AnalysisRecord.content_sha256 == content_sha256,
                    AnalysisRecord.state == AnalysisState.COMPLETED.value,
                )
                .order_by(AnalysisRecord.created_at.desc(), AnalysisRecord.analysis_id)
                .limit(limit)
            )
            return tuple(_row_to_summary(row) for row in session.execute(stmt))

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
