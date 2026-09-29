"""`record_ai_enrichment_call` and the persisted record (`EXP-01` slice 4)."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from sqlalchemy import text

from trusttable_backend.analysis.service import (
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
    analysis = create_analysis(store)
    store.update_ai_enrichment(analysis.analysis_id, lambda _: None)
    legacy = store.get(analysis.analysis_id)
    assert legacy is not None
    assert legacy.ai_enrichment is None

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


def test_a_stale_whole_analysis_write_cannot_revert_a_recorded_call_in_memory() -> None:
    store = AnalysisStore()
    analysis = create_analysis(store)
    stale = store.get(analysis.analysis_id)
    assert stale is not None and stale.ai_enrichment == AiEnrichmentRecord()

    _record(store, analysis.analysis_id, EnrichmentOutcome.ACCEPTED)
    store.replace(replace(stale, rules=()))

    kept = store.get(analysis.analysis_id)
    assert kept is not None and kept.ai_enrichment is not None
    assert kept.ai_enrichment.accepted_count == 1


def test_a_stale_whole_analysis_write_cannot_revert_a_recorded_call_in_sql(
    tmp_path: Path,
) -> None:
    """The reviewed counterexample: a writer reads the analysis with a zero
    record, another request records a call, then the first writer replaces
    the whole row with its stale copy."""
    store, engine = _sql_store(tmp_path)
    analysis = create_analysis(store)
    stale = store.get(analysis.analysis_id)
    assert stale is not None and stale.ai_enrichment == AiEnrichmentRecord()

    _record(store, analysis.analysis_id, EnrichmentOutcome.ACCEPTED)
    store.replace(replace(stale, rules=()))

    kept = store.get(analysis.analysis_id)
    assert kept is not None and kept.ai_enrichment is not None
    assert kept.ai_enrichment.accepted_count == 1
    engine.dispose()  # type: ignore[attr-defined]


def test_whole_analysis_writes_racing_recordings_lose_no_count(tmp_path: Path) -> None:
    store, engine = _sql_store(tmp_path)
    analysis = create_analysis(store)
    stale = store.get(analysis.analysis_id)
    assert stale is not None

    def rewrite() -> None:
        store.replace(replace(stale, rules=()))

    threads = []
    for _ in range(20):
        threads.append(
            threading.Thread(
                target=_record, args=(store, analysis.analysis_id, EnrichmentOutcome.ACCEPTED)
            )
        )
        threads.append(threading.Thread(target=rewrite))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    record = store.get(analysis.analysis_id).ai_enrichment  # type: ignore[union-attr]
    assert record is not None
    assert record.accepted_count == 20
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
