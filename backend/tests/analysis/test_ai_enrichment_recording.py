"""`record_ai_enrichment_call` and the persisted record (`EXP-01` slice 4)."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from sqlalchemy import text

from trusttable_backend.analysis.service import (
    Analysis,
    AnalysisStore,
    create_analysis,
    record_ai_enrichment_call,
)
from trusttable_backend.config import Settings
from trusttable_backend.domain.ai_enrichment import (
    AiEnrichmentRecord,
    EnrichmentModelLocation,
    EnrichmentOutcome,
)
from trusttable_backend.persistence import SqlAnalysisStore, build_engine, run_migrations


def _sql_store(tmp_path: Path) -> tuple[SqlAnalysisStore, object]:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'enrichment.db'}",
        data_directory=str(tmp_path),
    )
    engine = build_engine(settings)
    run_migrations(settings)
    return SqlAnalysisStore(engine), engine


def _record(store: object, analysis_id: str, outcome: EnrichmentOutcome) -> None:
    record_ai_enrichment_call(
        store,  # type: ignore[arg-type]
        analysis_id,
        outcome=outcome,
        evidence_sent=True,
        confirmed_context_sent=False,
        location=EnrichmentModelLocation.LOCAL,
    )


def test_a_new_analysis_starts_with_the_zero_record() -> None:
    analysis = create_analysis(AnalysisStore())

    assert analysis.ai_enrichment == AiEnrichmentRecord()


def test_recording_adds_one_attempt_and_leaves_the_rest_of_the_analysis_alone() -> None:
    store = AnalysisStore()
    analysis = create_analysis(store)

    _record(store, analysis.analysis_id, EnrichmentOutcome.REJECTED)

    updated = store.get(analysis.analysis_id)
    assert updated is not None
    assert updated.ai_enrichment is not None
    assert updated.ai_enrichment.rejected_count == 1
    assert updated.ai_enrichment.evidence_sent_to_model
    assert not updated.ai_enrichment.confirmed_context_sent_to_model
    assert replace(updated, ai_enrichment=analysis.ai_enrichment) == analysis


def test_an_analysis_without_a_record_is_never_started_counting() -> None:
    store = AnalysisStore()
    legacy: Analysis = replace(create_analysis(store), ai_enrichment=None)
    store.replace(legacy)

    _record(store, legacy.analysis_id, EnrichmentOutcome.ACCEPTED)

    assert store.get(legacy.analysis_id) == legacy


def test_an_unknown_analysis_is_ignored() -> None:
    _record(AnalysisStore(), "missing", EnrichmentOutcome.ACCEPTED)


def test_concurrent_recordings_do_not_lose_counts(tmp_path: Path) -> None:
    store, engine = _sql_store(tmp_path)
    analysis = create_analysis(store)
    outcomes = [EnrichmentOutcome.ACCEPTED, EnrichmentOutcome.REJECTED] * 20
    threads = [
        threading.Thread(target=_record, args=(store, analysis.analysis_id, outcome))
        for outcome in outcomes
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    record = store.get(analysis.analysis_id).ai_enrichment  # type: ignore[union-attr]
    assert record is not None
    assert (record.accepted_count, record.rejected_count) == (20, 20)
    engine.dispose()  # type: ignore[attr-defined]


def test_the_record_round_trips_and_a_null_column_means_not_recorded(tmp_path: Path) -> None:
    store, engine = _sql_store(tmp_path)
    analysis = create_analysis(store)
    _record(store, analysis.analysis_id, EnrichmentOutcome.PROVIDER_ERROR)
    stored = store.get(analysis.analysis_id)
    assert stored is not None
    assert stored.ai_enrichment is not None
    assert stored.ai_enrichment.provider_error_count == 1
    assert stored.ai_enrichment.model_location is EnrichmentModelLocation.LOCAL

    with engine.begin() as connection:  # type: ignore[attr-defined]
        connection.execute(text("UPDATE analyses SET ai_enrichment_json = NULL"))

    legacy = store.get(analysis.analysis_id)
    assert legacy is not None
    assert legacy.ai_enrichment is None
    _record(store, analysis.analysis_id, EnrichmentOutcome.ACCEPTED)
    assert store.get(analysis.analysis_id).ai_enrichment is None  # type: ignore[union-attr]
    engine.dispose()  # type: ignore[attr-defined]


def test_the_stored_record_holds_counters_and_flags_only(tmp_path: Path) -> None:
    store, engine = _sql_store(tmp_path)
    analysis = create_analysis(store)
    _record(store, analysis.analysis_id, EnrichmentOutcome.ACCEPTED)

    with engine.connect() as connection:  # type: ignore[attr-defined]
        raw = connection.execute(text("SELECT ai_enrichment_json FROM analyses")).scalar_one()

    body = raw if isinstance(raw, str) else str(raw)
    for forbidden in ("http", "prompt", "model_name", "llama", "base_url"):
        assert forbidden not in body.lower()
    engine.dispose()  # type: ignore[attr-defined]
