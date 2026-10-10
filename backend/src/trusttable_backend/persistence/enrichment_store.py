"""`SqlEnrichmentStore` (`UX-05b`): durable storage of per-finding AI
enrichments in `models.FindingEnrichmentRecord`.

All state transitions are guarded so that a stale worker can never overwrite a
newer attempt, and a restart can never leave a row `preparing`:

- `begin` is the only way to start work. It is idempotent for the same
  binding, bounded by `max_preparing`, and never stores a row for an analysis
  that no longer exists.
- `complete` only finishes a row that is still `preparing` under the binding
  the worker started with.
- `interrupt_preparing` is called once at startup, before any worker exists.

Deleting an analysis deletes its enrichments (`SqlAnalysisStore.delete`).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import func, select, update
from sqlalchemy.engine import Engine

from ..domain.explanation import FindingExplanation
from ..domain.finding_enrichment import EnrichmentReason, EnrichmentStatus, FindingEnrichment
from . import serializers
from .database import build_session_factory
from .models import AnalysisRecord, FindingEnrichmentRecord

#: The disclosure a row carries before any attempt completes.
AI_CALL_NOT_ATTEMPTED = "not_attempted"


class BeginOutcome(StrEnum):
    STARTED = "started"
    EXISTING = "existing"
    BUSY = "busy"
    ANALYSIS_MISSING = "analysis_missing"


@dataclass(frozen=True, slots=True)
class BeginResult:
    outcome: BeginOutcome
    enrichment: FindingEnrichment | None


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _to_enrichment(row: FindingEnrichmentRecord) -> FindingEnrichment:
    status = EnrichmentStatus(row.status)
    reason = EnrichmentReason(row.reason) if row.reason is not None else None
    explanation: FindingExplanation | None = None
    if status is EnrichmentStatus.READY:
        try:
            decoded = serializers.decode(row.result_json)
            if not isinstance(decoded, FindingExplanation):
                raise TypeError("saved result is not an explanation")
            explanation = decoded
        except Exception:
            # A corrupted saved result is never served: the row reads as a
            # failure and can be requested again.
            status = EnrichmentStatus.FAILED
            reason = EnrichmentReason.UNREADABLE
    return FindingEnrichment(
        analysis_id=row.analysis_id,
        finding_id=row.finding_id,
        status=status,
        binding_digest=row.binding_digest,
        reason=reason,
        ai_call_status=row.ai_call_status,
        evidence_sent_to_model=row.evidence_sent_to_model,
        confirmed_context_sent_to_model=row.confirmed_context_sent_to_model,
        explanation=explanation,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


class SqlEnrichmentStore:
    """A durable per-finding AI enrichment store."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = build_session_factory(engine)
        self._lock = threading.Lock()

    def get(self, analysis_id: str, finding_id: str) -> FindingEnrichment | None:
        with self._session_factory() as session:
            row = session.get(FindingEnrichmentRecord, (analysis_id, finding_id))
            return _to_enrichment(row) if row is not None else None

    def count_preparing(self) -> int:
        with self._session_factory() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(FindingEnrichmentRecord)
                    .where(FindingEnrichmentRecord.status == EnrichmentStatus.PREPARING.value)
                )
                or 0
            )

    def begin(
        self,
        analysis_id: str,
        finding_id: str,
        *,
        binding_digest: str,
        evidence_sent_to_model: bool,
        confirmed_context_sent_to_model: bool,
        max_preparing: int,
        now: datetime | None = None,
    ) -> BeginResult:
        """Start (or find) the enrichment for the finding under `binding_digest`.

        - A `preparing` or `ready` row with the same binding is returned
          unchanged (`EXISTING`): starting is idempotent and cannot be used to
          re-run a model call.
        - Otherwise the row becomes `preparing` under the new binding
          (`STARTED`), unless `max_preparing` rows are already preparing
          (`BUSY`). A `failed` or stale row is thereby retried or superseded;
          any worker still running for the old binding can no longer complete
          it.
        - The sent flags are conservative until the attempt completes.
        """
        moment = _iso(now or datetime.now(UTC))
        with self._lock, self._session_factory() as session:
            row = session.get(FindingEnrichmentRecord, (analysis_id, finding_id))
            if (
                row is not None
                and row.binding_digest == binding_digest
                and row.status in (EnrichmentStatus.PREPARING.value, EnrichmentStatus.READY.value)
            ):
                return BeginResult(BeginOutcome.EXISTING, _to_enrichment(row))
            others_preparing = int(
                session.scalar(
                    select(func.count())
                    .select_from(FindingEnrichmentRecord)
                    .where(
                        FindingEnrichmentRecord.status == EnrichmentStatus.PREPARING.value,
                        (FindingEnrichmentRecord.analysis_id != analysis_id)
                        | (FindingEnrichmentRecord.finding_id != finding_id),
                    )
                )
                or 0
            )
            if others_preparing >= max_preparing:
                return BeginResult(BeginOutcome.BUSY, None)
            if row is None:
                row = FindingEnrichmentRecord(
                    analysis_id=analysis_id, finding_id=finding_id, created_at=moment
                )
                session.add(row)
            row.status = EnrichmentStatus.PREPARING.value
            row.binding_digest = binding_digest
            row.reason = None
            row.ai_call_status = AI_CALL_NOT_ATTEMPTED
            row.evidence_sent_to_model = evidence_sent_to_model
            row.confirmed_context_sent_to_model = confirmed_context_sent_to_model
            row.result_json = None
            row.updated_at = moment
            session.flush()
            # The write above holds SQLite's write lock, so a concurrent
            # `delete` either already committed (seen here) or will remove this
            # row after we commit: no enrichment outlives its analysis.
            if session.get(AnalysisRecord, analysis_id) is None:
                session.rollback()
                return BeginResult(BeginOutcome.ANALYSIS_MISSING, None)
            session.commit()
            return BeginResult(BeginOutcome.STARTED, _to_enrichment(row))

    def complete(
        self,
        analysis_id: str,
        finding_id: str,
        *,
        binding_digest: str,
        status: EnrichmentStatus,
        reason: EnrichmentReason | None,
        ai_call_status: str,
        evidence_sent_to_model: bool,
        confirmed_context_sent_to_model: bool,
        explanation: FindingExplanation | None,
        now: datetime | None = None,
    ) -> bool:
        """Finish a `preparing` row, only under the binding the worker
        started with. Returns whether it applied (it does not for a row that
        was superseded, deleted or already finished)."""
        if status is EnrichmentStatus.PREPARING:
            raise ValueError("complete() finishes an enrichment; it cannot leave it preparing")
        if (status is EnrichmentStatus.READY) != (explanation is not None):
            raise ValueError("a saved explanation exists exactly when the enrichment is ready")
        with self._lock, self._session_factory() as session:
            result = session.execute(
                update(FindingEnrichmentRecord)
                .where(
                    FindingEnrichmentRecord.analysis_id == analysis_id,
                    FindingEnrichmentRecord.finding_id == finding_id,
                    FindingEnrichmentRecord.binding_digest == binding_digest,
                    FindingEnrichmentRecord.status == EnrichmentStatus.PREPARING.value,
                )
                .values(
                    status=status.value,
                    reason=reason.value if reason is not None else None,
                    ai_call_status=ai_call_status,
                    evidence_sent_to_model=evidence_sent_to_model,
                    confirmed_context_sent_to_model=confirmed_context_sent_to_model,
                    result_json=serializers.encode(explanation) if explanation else None,
                    updated_at=_iso(now or datetime.now(UTC)),
                )
            )
            session.commit()
            return bool(result.rowcount)  # type: ignore[attr-defined]

    def interrupt_preparing(self, now: datetime | None = None) -> tuple[FindingEnrichment, ...]:
        """Fail every `preparing` row (`interrupted`). Called once at startup,
        before any worker exists: a row still `preparing` then belongs to a
        process that is gone. Returns the rows as they were, so the caller can
        record the attempt they may have made."""
        moment = _iso(now or datetime.now(UTC))
        with self._lock, self._session_factory() as session:
            rows = session.scalars(
                select(FindingEnrichmentRecord).where(
                    FindingEnrichmentRecord.status == EnrichmentStatus.PREPARING.value
                )
            ).all()
            interrupted = tuple(_to_enrichment(row) for row in rows)
            for row in rows:
                row.status = EnrichmentStatus.FAILED.value
                row.reason = EnrichmentReason.INTERRUPTED.value
                row.ai_call_status = "attempted_provider_error"
                row.updated_at = moment
            session.commit()
            return interrupted
