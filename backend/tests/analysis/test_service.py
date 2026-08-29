"""Tests for in-memory analysis orchestration (`API-01` enabling slice,
`WP-023`).

Covers AC-01..AC-22: `AnalysisState`/`Analysis` construction invariants,
`create_analysis` correctness including the real-bytes demo-CSV identity
proof (AC-04) and distinct-ID proof (AC-05), `run_analysis`'s full
pipeline wiring with cross-package equivalence proofs against
directly-called `PROF-03`/`DET-01`+`DET-02`+`DET-SEC-01`/`RISK-01`
functions (AC-07/AC-08), idempotency (AC-09), fault-injection
safe-failure isolation (AC-10), not-found/not-completed semantics for
every getter (AC-11..AC-13), queued-only cancellation semantics
(AC-14/AC-15), `AnalysisStore` behavior (AC-16), `AnalysisNotFoundError`'s
carried ID (AC-17), the fixed exposure-disabled proof (AC-18),
no-`eval`/`exec` and no-FastAPI/SQLAlchemy-import proofs (AC-19/AC-20),
and a two-independent-run determinism proof (AC-22). AC-21 (format/
lint/mypy/full-suite) and AC-23 (documentation updates) are evidenced
outside this file.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trusttable_backend.analysis.service import (
    Analysis,
    AnalysisFailure,
    AnalysisNotFoundError,
    AnalysisState,
    AnalysisStore,
    cancel_analysis,
    create_analysis,
    get_findings,
    get_profile,
    get_status,
    run_analysis,
)
from trusttable_backend.demo_data import SEED, generate
from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    FindingCandidate,
    SecurityExposureState,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.domain.parsing import (
    Dataset,
    DatasetFormat,
    DatasetSourceType,
    SampleMetadata,
    SamplingScope,
)
from trusttable_backend.domain.value_objects import ColumnReference, Severity
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.profiling.schemas import DatasetProfile
from trusttable_backend.risk.scoring import (
    TrustAssessment,
    TrustLabel,
    calculate_finding_priority_scores,
    calculate_trust_assessment,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"
SERVICE_MODULE_PATH = (
    REPO_ROOT / "backend" / "src" / "trusttable_backend" / "analysis" / "service.py"
)

FIXED_NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
NO_EXPOSURE = SecurityExposureState(model_provider_enabled=False, sample_transmission_enabled=False)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_dataset(**overrides: object) -> Dataset:
    fields: dict[str, object] = {
        "dataset_id": "dataset-1",
        "original_filename": "sales_demo.csv",
        "stored_filename": "sales_demo.csv",
        "format": DatasetFormat.CSV,
        "byte_size": 10,
        "content_hash": "deadbeef",
        "selected_worksheet": None,
        "created_at": FIXED_NOW,
        "deleted_at": None,
        "storage_location": "demo-data/sales_demo.csv",
        "source_type": DatasetSourceType.BUNDLED_DEMO,
    }
    fields.update(overrides)
    return Dataset(**fields)  # type: ignore[arg-type]


def _make_analysis(**overrides: object) -> Analysis:
    fields: dict[str, object] = {
        "analysis_id": "analysis-1",
        "dataset": _make_dataset(),
        "state": AnalysisState.QUEUED,
        "security_exposure": NO_EXPOSURE,
        "dataset_profile": None,
        "findings": (),
        "priority_scores": (),
        "trust_assessment": None,
        "failure": None,
        "created_at": FIXED_NOW,
        "started_at": None,
        "completed_at": None,
        "failed_at": None,
        "cancelled_at": None,
    }
    fields.update(overrides)
    return Analysis(**fields)  # type: ignore[arg-type]


def _valid_profile() -> DatasetProfile:
    columns = (ColumnReference(original_name="col", internal_key="col", ordinal=0),)
    rows: tuple[tuple[str | None, ...], ...] = (("value",),)
    sampling = SampleMetadata(scope=SamplingScope.FULL, population_size=1, sample_size=1)
    return compute_dataset_profile(columns, rows, sampling, as_of=FIXED_NOW.date())


def _valid_trust_assessment() -> TrustAssessment:
    return calculate_trust_assessment((), (), security_exposure=NO_EXPOSURE)


def _make_completed_analysis(**overrides: object) -> Analysis:
    fields: dict[str, object] = {
        "state": AnalysisState.COMPLETED,
        "dataset_profile": _valid_profile(),
        "findings": (),
        "priority_scores": (),
        "trust_assessment": _valid_trust_assessment(),
        "completed_at": FIXED_NOW,
    }
    fields.update(overrides)
    return _make_analysis(**fields)


def _make_finding() -> FindingCandidate:
    column = ColumnReference(original_name="col", internal_key="col", ordinal=0)
    return FindingCandidate(
        detector_id="test.detector",
        detector_version="1",
        category=DetectorCategory.STRUCTURAL,
        severity=Severity.LOW,
        confidence=1.0,
        calculated_observation="test observation",
        affected_columns=(column,),
        affected_row_references=(),
        evidence_ids=("evidence-1",),
        default_remediation_template_key=None,
        default_validation_rule_template_key=None,
    )


def _run_direct_pipeline(
    now: datetime,
) -> tuple[DatasetProfile, tuple[FindingCandidate, ...], TrustAssessment]:
    """Independently reproduce `run_analysis`'s exact call chain, for
    AC-07/AC-08's cross-package equivalence proofs — matches `RISK-01`'s
    own `_run_real_demo_csv_assessment` pattern (`WP-022`).
    """
    generated = generate(seed=SEED)
    content = generated.to_csv_text().encode("utf-8")
    parsed = parse_csv(content)
    columns = parsed.parsed_dataset.columns

    dataset_profile = compute_dataset_profile(
        columns, parsed.rows, parsed.parsed_dataset.sampling, as_of=now.date()
    )
    mapping_rows = tuple(
        {column.internal_key: row[column.ordinal] for column in columns} for row in parsed.rows
    )
    results = run_detectors(
        list(DETECTORS),
        dataset_profile=dataset_profile,
        rows=mapping_rows,
        row_references=parsed.parsed_dataset.row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=now,
    )
    findings = tuple(finding for result in results for finding in result.findings)
    priority_scores = calculate_finding_priority_scores(findings, dataset_profile=dataset_profile)
    trust_assessment = calculate_trust_assessment(
        findings, priority_scores, security_exposure=NO_EXPOSURE
    )
    return dataset_profile, findings, trust_assessment


# ---------------------------------------------------------------------------
# AC-01: AnalysisState
# ---------------------------------------------------------------------------


def test_analysis_state_has_exactly_eight_values() -> None:
    assert {member.value for member in AnalysisState} == {
        "queued",
        "validating",
        "parsing",
        "profiling",
        "detecting",
        "completed",
        "failed",
        "cancelled",
    }


# ---------------------------------------------------------------------------
# AC-02: Analysis construction invariants
# ---------------------------------------------------------------------------


def test_analysis_queued_baseline_is_valid() -> None:
    analysis = _make_analysis()
    assert analysis.state is AnalysisState.QUEUED


def test_analysis_completed_baseline_is_valid() -> None:
    analysis = _make_completed_analysis()
    assert analysis.state is AnalysisState.COMPLETED


def test_analysis_completed_requires_dataset_profile() -> None:
    with pytest.raises(ValueError, match="dataset_profile"):
        _make_completed_analysis(dataset_profile=None)


def test_analysis_completed_requires_trust_assessment() -> None:
    with pytest.raises(ValueError, match="trust_assessment"):
        _make_completed_analysis(trust_assessment=None)


def test_analysis_completed_requires_completed_at() -> None:
    with pytest.raises(ValueError, match="completed_at"):
        _make_completed_analysis(completed_at=None)


def test_analysis_non_completed_rejects_dataset_profile() -> None:
    with pytest.raises(ValueError, match="dataset_profile"):
        _make_analysis(dataset_profile=_valid_profile())


def test_analysis_non_completed_rejects_findings() -> None:
    with pytest.raises(ValueError, match="findings"):
        _make_analysis(findings=(_make_finding(),), priority_scores=(50.0,))


def test_analysis_non_completed_rejects_trust_assessment() -> None:
    with pytest.raises(ValueError, match="trust_assessment"):
        _make_analysis(trust_assessment=_valid_trust_assessment())


def test_analysis_non_completed_rejects_completed_at() -> None:
    with pytest.raises(ValueError, match="completed_at"):
        _make_analysis(completed_at=FIXED_NOW)


def test_analysis_failed_requires_failure() -> None:
    with pytest.raises(ValueError, match="failure"):
        _make_analysis(state=AnalysisState.FAILED, failed_at=FIXED_NOW)


def test_analysis_failed_requires_failed_at() -> None:
    with pytest.raises(ValueError, match="failed_at"):
        _make_analysis(
            state=AnalysisState.FAILED,
            failure=AnalysisFailure(code="test.failure", message="a message"),
        )


def test_analysis_non_failed_rejects_failure() -> None:
    with pytest.raises(ValueError, match="failure"):
        _make_analysis(failure=AnalysisFailure(code="test.failure", message="a message"))


def test_analysis_non_failed_rejects_failed_at() -> None:
    with pytest.raises(ValueError, match="failed_at"):
        _make_analysis(failed_at=FIXED_NOW)


def test_analysis_cancelled_requires_cancelled_at() -> None:
    with pytest.raises(ValueError, match="cancelled_at"):
        _make_analysis(state=AnalysisState.CANCELLED)


def test_analysis_non_cancelled_rejects_cancelled_at() -> None:
    with pytest.raises(ValueError, match="cancelled_at"):
        _make_analysis(cancelled_at=FIXED_NOW)


def test_analysis_priority_scores_must_match_findings_length() -> None:
    with pytest.raises(ValueError, match="priority_scores"):
        _make_completed_analysis(findings=(), priority_scores=(50.0,))


# ---------------------------------------------------------------------------
# AC-03/AC-04/AC-05: create_analysis
# ---------------------------------------------------------------------------


def test_create_analysis_produces_queued_analysis() -> None:
    store = AnalysisStore()
    analysis = create_analysis(store)

    assert analysis.state is AnalysisState.QUEUED
    assert analysis.analysis_id
    assert analysis.dataset.source_type is DatasetSourceType.BUNDLED_DEMO
    assert analysis.dataset.format is DatasetFormat.CSV
    assert analysis.dataset.content_hash
    assert analysis.dataset.byte_size > 0
    assert analysis.dataset_profile is None
    assert analysis.findings == ()
    assert analysis.priority_scores == ()
    assert analysis.trust_assessment is None
    assert analysis.failure is None


def test_create_analysis_demo_bytes_match_committed_file() -> None:
    store = AnalysisStore()
    analysis = create_analysis(store)

    committed_bytes = DEMO_CSV_PATH.read_bytes()
    expected_hash = hashlib.sha256(committed_bytes).hexdigest()

    assert analysis.dataset.content_hash == expected_hash
    assert analysis.dataset.byte_size == len(committed_bytes)


def test_create_analysis_produces_distinct_ids() -> None:
    store = AnalysisStore()
    first = create_analysis(store)
    second = create_analysis(store)

    assert first.analysis_id != second.analysis_id
    assert first.dataset.dataset_id != second.dataset.dataset_id


# ---------------------------------------------------------------------------
# AC-06/AC-07/AC-08: run_analysis pipeline wiring and equivalence proofs
# ---------------------------------------------------------------------------


def test_run_analysis_completes_queued_analysis() -> None:
    store = AnalysisStore()
    created = create_analysis(store)

    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert completed.state is AnalysisState.COMPLETED
    assert completed.dataset_profile is not None
    assert completed.priority_scores == calculate_finding_priority_scores(
        completed.findings, dataset_profile=completed.dataset_profile
    )
    assert completed.trust_assessment is not None
    assert completed.completed_at is not None
    assert completed.failure is None
    assert completed.failed_at is None
    assert completed.cancelled_at is None


def test_run_analysis_matches_direct_pipeline_calls() -> None:
    store = AnalysisStore()
    created = create_analysis(store)
    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)
    assert completed.dataset_profile is not None

    expected_profile, expected_findings, _ = _run_direct_pipeline(FIXED_NOW)

    assert completed.findings == expected_findings
    # `timing` carries a real wall-clock start/end and is expected to
    # differ between two independently computed profiles; every other
    # field must match exactly.
    assert completed.dataset_profile.schema_version == expected_profile.schema_version
    assert completed.dataset_profile.dataset_metrics == expected_profile.dataset_metrics
    assert completed.dataset_profile.column_profiles == expected_profile.column_profiles
    assert completed.dataset_profile.sampling == expected_profile.sampling
    assert completed.dataset_profile.warnings == expected_profile.warnings


def test_run_analysis_matches_direct_trust_assessment() -> None:
    store = AnalysisStore()
    created = create_analysis(store)
    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    _, _, expected_trust_assessment = _run_direct_pipeline(FIXED_NOW)

    assert completed.trust_assessment == expected_trust_assessment
    assert completed.trust_assessment is not None
    assert completed.trust_assessment.finding_count > 0
    assert completed.trust_assessment.label is not TrustLabel.HIGH_CONFIDENCE


# ---------------------------------------------------------------------------
# AC-09: idempotency
# ---------------------------------------------------------------------------


def test_run_analysis_is_idempotent() -> None:
    store = AnalysisStore()
    created = create_analysis(store)

    first = run_analysis(store, created.analysis_id, now=FIXED_NOW)
    second = run_analysis(store, created.analysis_id, now=FIXED_NOW)
    assert first == second

    # A different `now` would change detector findings if the pipeline
    # were re-executed; an unchanged result proves it was not.
    third = run_analysis(store, created.analysis_id, now=datetime(2020, 1, 1, tzinfo=UTC))
    assert third == first


# ---------------------------------------------------------------------------
# AC-10: fault-injection safe failure
# ---------------------------------------------------------------------------


def test_run_analysis_isolates_pipeline_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AnalysisStore()
    created = create_analysis(store)

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic pipeline failure for AC-10, must not leak")

    monkeypatch.setattr("trusttable_backend.analysis.service.parse_csv", _boom)

    failed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert failed.state is AnalysisState.FAILED
    assert failed.failure is not None
    assert failed.failure.code == "analysis.pipeline_failed"
    assert "synthetic" not in failed.failure.message
    assert "RuntimeError" not in failed.failure.message
    assert failed.failed_at is not None
    assert failed.dataset_profile is None
    assert failed.findings == ()
    assert failed.priority_scores == ()
    assert failed.trust_assessment is None


# ---------------------------------------------------------------------------
# AC-11/AC-12/AC-13: getters
# ---------------------------------------------------------------------------


def test_get_status_known_and_unknown() -> None:
    store = AnalysisStore()
    created = create_analysis(store)

    assert get_status(store, created.analysis_id) == created
    with pytest.raises(AnalysisNotFoundError):
        get_status(store, "unknown-id")


def test_get_profile_queued_and_completed() -> None:
    store = AnalysisStore()
    created = create_analysis(store)
    assert get_profile(store, created.analysis_id) is None

    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)
    assert get_profile(store, completed.analysis_id) is completed.dataset_profile
    assert get_profile(store, completed.analysis_id) is not None

    with pytest.raises(AnalysisNotFoundError):
        get_profile(store, "unknown-id")


def test_get_profile_cancelled_and_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AnalysisStore()

    cancelled_created = create_analysis(store)
    cancelled = cancel_analysis(store, cancelled_created.analysis_id)
    assert get_profile(store, cancelled.analysis_id) is None

    failed_created = create_analysis(store)

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic")

    monkeypatch.setattr("trusttable_backend.analysis.service.parse_csv", _boom)
    failed = run_analysis(store, failed_created.analysis_id, now=FIXED_NOW)
    assert get_profile(store, failed.analysis_id) is None


def test_get_findings_queued_and_completed() -> None:
    store = AnalysisStore()
    created = create_analysis(store)
    assert get_findings(store, created.analysis_id) == ()

    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)
    assert get_findings(store, completed.analysis_id) == completed.findings

    with pytest.raises(AnalysisNotFoundError):
        get_findings(store, "unknown-id")


def test_get_findings_cancelled_is_empty() -> None:
    store = AnalysisStore()
    created = create_analysis(store)
    cancelled = cancel_analysis(store, created.analysis_id)
    assert get_findings(store, cancelled.analysis_id) == ()


# ---------------------------------------------------------------------------
# AC-14/AC-15: cancel_analysis
# ---------------------------------------------------------------------------


def test_cancel_analysis_queued_transitions_to_cancelled() -> None:
    store = AnalysisStore()
    created = create_analysis(store)

    cancelled = cancel_analysis(store, created.analysis_id)

    assert cancelled.state is AnalysisState.CANCELLED
    assert cancelled.cancelled_at is not None
    assert cancelled.dataset_profile is None
    assert cancelled.findings == ()
    assert cancelled.priority_scores == ()
    assert cancelled.trust_assessment is None


def test_cancel_analysis_completed_is_unchanged() -> None:
    store = AnalysisStore()
    created = create_analysis(store)
    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert cancel_analysis(store, completed.analysis_id) == completed


def test_cancel_analysis_already_cancelled_is_unchanged() -> None:
    store = AnalysisStore()
    created = create_analysis(store)
    cancelled = cancel_analysis(store, created.analysis_id)

    assert cancel_analysis(store, cancelled.analysis_id) == cancelled


def test_cancel_analysis_failed_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    store = AnalysisStore()
    created = create_analysis(store)

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic")

    monkeypatch.setattr("trusttable_backend.analysis.service.parse_csv", _boom)
    failed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert cancel_analysis(store, failed.analysis_id) == failed


def test_cancel_analysis_unknown_id_raises() -> None:
    store = AnalysisStore()
    with pytest.raises(AnalysisNotFoundError):
        cancel_analysis(store, "unknown-id")


# ---------------------------------------------------------------------------
# AC-16: AnalysisStore
# ---------------------------------------------------------------------------


def test_analysis_store_add_get_replace() -> None:
    store = AnalysisStore()
    analysis = _make_analysis()

    store.add(analysis)
    assert store.get(analysis.analysis_id) == analysis
    assert store.get("unknown-id") is None

    replaced = _make_analysis(
        analysis_id=analysis.analysis_id, state=AnalysisState.CANCELLED, cancelled_at=FIXED_NOW
    )
    store.replace(replaced)
    assert store.get(analysis.analysis_id) == replaced


# ---------------------------------------------------------------------------
# AC-17: AnalysisNotFoundError
# ---------------------------------------------------------------------------


def test_analysis_not_found_error_carries_requested_id() -> None:
    error = AnalysisNotFoundError("missing-id")
    assert error.analysis_id == "missing-id"


# ---------------------------------------------------------------------------
# AC-18: exposure-disabled proof
# ---------------------------------------------------------------------------


def test_create_analysis_security_exposure_always_disabled() -> None:
    store = AnalysisStore()
    analysis = create_analysis(store)

    assert analysis.security_exposure == SecurityExposureState(
        model_provider_enabled=False, sample_transmission_enabled=False
    )


# ---------------------------------------------------------------------------
# AC-19/AC-20: no eval/exec, no FastAPI/SQLAlchemy import
# ---------------------------------------------------------------------------


def test_no_eval_or_exec_in_service_module() -> None:
    source = SERVICE_MODULE_PATH.read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


def test_no_fastapi_or_sqlalchemy_import_in_service_module() -> None:
    # Scoped to import lines only — the module's own docstring legitimately
    # discusses "no FastAPI route" while explaining this package's scope,
    # which a naive whole-file substring scan would misreport as a hit.
    import_lines = [
        line
        for line in SERVICE_MODULE_PATH.read_text(encoding="utf-8").splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    assert not any("fastapi" in line.lower() for line in import_lines)
    assert not any("sqlalchemy" in line.lower() for line in import_lines)


# ---------------------------------------------------------------------------
# AC-22: two-independent-run determinism
# ---------------------------------------------------------------------------


def test_two_independent_round_trips_are_deterministic() -> None:
    store_one = AnalysisStore()
    created_one = create_analysis(store_one)
    completed_one = run_analysis(store_one, created_one.analysis_id, now=FIXED_NOW)

    store_two = AnalysisStore()
    created_two = create_analysis(store_two)
    completed_two = run_analysis(store_two, created_two.analysis_id, now=FIXED_NOW)

    assert completed_one.findings == completed_two.findings
    assert completed_one.priority_scores == completed_two.priority_scores
    assert completed_one.trust_assessment == completed_two.trust_assessment
