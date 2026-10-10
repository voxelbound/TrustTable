"""`SqlEnrichmentStore` (`UX-05b`): guarded transitions, idempotent and bounded
start, no row for a missing analysis, and no superseded worker overwriting a
newer attempt."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import Engine

from trusttable_backend.analysis import create_analysis
from trusttable_backend.config import get_settings
from trusttable_backend.domain.explanation import FindingExplanation
from trusttable_backend.domain.finding_enrichment import EnrichmentReason, EnrichmentStatus
from trusttable_backend.domain.value_objects import Provenance
from trusttable_backend.persistence import SqlAnalysisStore, build_engine, run_migrations
from trusttable_backend.persistence.enrichment_store import (
    BeginOutcome,
    BeginResult,
    SqlEnrichmentStore,
)


@pytest.fixture
def engine() -> Iterator[Engine]:
    settings = get_settings()
    run_migrations(settings)
    built = build_engine(settings)
    yield built
    built.dispose()


@pytest.fixture
def stores(engine: Engine) -> tuple[SqlAnalysisStore, SqlEnrichmentStore]:
    return SqlAnalysisStore(engine), SqlEnrichmentStore(engine)


def _explanation() -> FindingExplanation:
    return FindingExplanation(
        narrative="A saved narrative.",
        provenance=Provenance.AI_INTERPRETATION,
        referenced_evidence_ids=(),
        referenced_columns=(),
        provider_name="mock",
        model_identifier="mock-v1",
    )


def _begin(
    store: SqlEnrichmentStore,
    analysis_id: str,
    finding_id: str = "0",
    binding: str = "b1",
    cap: int = 8,
) -> BeginResult:
    return store.begin(
        analysis_id,
        finding_id,
        binding_digest=binding,
        evidence_sent_to_model=True,
        confirmed_context_sent_to_model=False,
        max_preparing=cap,
    )


def _complete_ready(store: SqlEnrichmentStore, analysis_id: str, binding: str = "b1") -> bool:
    return store.complete(
        analysis_id,
        "0",
        binding_digest=binding,
        status=EnrichmentStatus.READY,
        reason=None,
        ai_call_status="attempted_accepted",
        evidence_sent_to_model=True,
        confirmed_context_sent_to_model=False,
        explanation=_explanation(),
    )


def test_begin_creates_a_preparing_row_with_conservative_disclosure(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id

    result = _begin(store, analysis_id)

    assert result.outcome is BeginOutcome.STARTED
    row = store.get(analysis_id, "0")
    assert row is not None
    assert row.status is EnrichmentStatus.PREPARING
    assert row.ai_call_status == "not_attempted"
    assert row.evidence_sent_to_model is True
    assert row.explanation is None and row.reason is None


def test_begin_is_idempotent_for_the_same_binding_while_preparing_or_ready(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id
    assert _begin(store, analysis_id).outcome is BeginOutcome.STARTED

    assert _begin(store, analysis_id).outcome is BeginOutcome.EXISTING
    assert _complete_ready(store, analysis_id) is True
    again = _begin(store, analysis_id)
    assert again.outcome is BeginOutcome.EXISTING
    assert again.enrichment is not None and again.enrichment.status is EnrichmentStatus.READY


def test_a_changed_binding_supersedes_and_the_old_worker_can_no_longer_complete_it(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id
    _begin(store, analysis_id, binding="old")

    assert _begin(store, analysis_id, binding="new").outcome is BeginOutcome.STARTED

    assert _complete_ready(store, analysis_id, binding="old") is False
    row = store.get(analysis_id, "0")
    assert row is not None and row.status is EnrichmentStatus.PREPARING
    assert row.binding_digest == "new"
    assert _complete_ready(store, analysis_id, binding="new") is True


def test_a_failed_row_is_restarted_by_begin(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id
    _begin(store, analysis_id)
    assert store.complete(
        analysis_id,
        "0",
        binding_digest="b1",
        status=EnrichmentStatus.FAILED,
        reason=EnrichmentReason.PROVIDER_ERROR,
        ai_call_status="attempted_provider_error",
        evidence_sent_to_model=True,
        confirmed_context_sent_to_model=False,
        explanation=None,
    )

    assert _begin(store, analysis_id).outcome is BeginOutcome.STARTED
    row = store.get(analysis_id, "0")
    assert row is not None and row.status is EnrichmentStatus.PREPARING
    assert row.reason is None


def test_begin_is_bounded_by_the_number_of_preparing_rows(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id
    assert _begin(store, analysis_id, "0", cap=2).outcome is BeginOutcome.STARTED
    assert _begin(store, analysis_id, "1", cap=2).outcome is BeginOutcome.STARTED

    assert _begin(store, analysis_id, "2", cap=2).outcome is BeginOutcome.BUSY
    assert store.get(analysis_id, "2") is None
    assert store.count_preparing() == 2
    # An already-preparing finding is found, not refused, at the bound.
    assert _begin(store, analysis_id, "0", cap=2).outcome is BeginOutcome.EXISTING
    # A new binding for a finding that already holds a slot reuses that slot.
    assert _begin(store, analysis_id, "0", binding="b2", cap=2).outcome is BeginOutcome.STARTED


def test_begin_stores_nothing_for_a_missing_analysis(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    _, store = stores

    assert _begin(store, "no-such-analysis").outcome is BeginOutcome.ANALYSIS_MISSING
    assert store.get("no-such-analysis", "0") is None
    assert store.count_preparing() == 0


def test_complete_applies_only_to_a_preparing_row(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id
    assert _complete_ready(store, analysis_id) is False  # no row
    _begin(store, analysis_id)
    assert _complete_ready(store, analysis_id) is True
    assert _complete_ready(store, analysis_id) is False  # already finished


def test_complete_refuses_to_leave_a_row_preparing_or_to_store_output_for_a_failure(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id
    _begin(store, analysis_id)

    with pytest.raises(ValueError):
        store.complete(
            analysis_id,
            "0",
            binding_digest="b1",
            status=EnrichmentStatus.PREPARING,
            reason=None,
            ai_call_status="x",
            evidence_sent_to_model=False,
            confirmed_context_sent_to_model=False,
            explanation=None,
        )
    with pytest.raises(ValueError):
        store.complete(
            analysis_id,
            "0",
            binding_digest="b1",
            status=EnrichmentStatus.FAILED,
            reason=EnrichmentReason.REJECTED,
            ai_call_status="attempted_rejected",
            evidence_sent_to_model=True,
            confirmed_context_sent_to_model=False,
            explanation=_explanation(),
        )


def test_the_saved_explanation_round_trips_exactly(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id
    _begin(store, analysis_id)
    _complete_ready(store, analysis_id)

    row = store.get(analysis_id, "0")

    assert row is not None
    assert row.explanation == _explanation()
    assert row.updated_at >= row.created_at
    assert row.updated_at.tzinfo is not None


def test_interrupt_preparing_fails_only_preparing_rows_and_returns_them(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    analysis_id = create_analysis(analyses).analysis_id
    _begin(store, analysis_id, "0")
    _complete_ready(store, analysis_id)
    _begin(store, analysis_id, "1")

    interrupted = store.interrupt_preparing(now=datetime(2026, 10, 10, tzinfo=UTC))

    assert [row.finding_id for row in interrupted] == ["1"]
    assert interrupted[0].status is EnrichmentStatus.PREPARING  # as it was found
    ready = store.get(analysis_id, "0")
    failed = store.get(analysis_id, "1")
    assert ready is not None and ready.status is EnrichmentStatus.READY
    assert failed is not None and failed.status is EnrichmentStatus.FAILED
    assert failed.reason is EnrichmentReason.INTERRUPTED
    assert store.count_preparing() == 0
    assert store.interrupt_preparing() == ()


def test_deleting_the_analysis_deletes_its_enrichments(
    stores: tuple[SqlAnalysisStore, SqlEnrichmentStore],
) -> None:
    analyses, store = stores
    kept = create_analysis(analyses).analysis_id
    removed = create_analysis(analyses).analysis_id
    _begin(store, kept)
    _begin(store, removed)
    _begin(store, removed, "1")

    assert analyses.delete(removed) is True

    assert store.get(removed, "0") is None and store.get(removed, "1") is None
    assert store.get(kept, "0") is not None
