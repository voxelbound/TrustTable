"""Tests for `DET-03` closure package 2 (D-061): the minimal Observation
foundation and its three `value_evidence` producers
`structural.mixed_types`, `consistency.inconsistent_date_formats` and
`completeness.concentrated_missingness`.

Follows `docs/detector-framework.md` §15's detector test contract. The
properties that matter most:

- an Observation has no severity, confidence or priority and one closed kind;
- the producers never emit a finding, so nothing can reach scoring, guidance or
  rules;
- no cell value is copied into an observation;
- a negative allowlist test fails if an Observation reaches the trust score,
  finding priority, an AI payload, an export or a report.
"""

from __future__ import annotations

import dataclasses
import json
import re
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import trusttable_backend
from tests.detectors.test_det03_slice1 import (
    ANALYSIS_TIMESTAMP,
    NO_EXPOSURE,
    make_profile,
)
from trusttable_backend.analysis import service as analysis_service
from trusttable_backend.analysis.service import (
    Analysis,
    AnalysisState,
    AnalysisStore,
    create_analysis_from_upload,
    run_analysis,
)
from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    ExecutionMetrics,
    SafeFailure,
)
from trusttable_backend.detectors.value_evidence import (
    DATE_FORMAT_FAMILIES,
    OBSERVATION_ONLY_DETECTOR_IDS,
    ConcentratedMissingnessDetector,
    InconsistentDateFormatsDetector,
    MixedTypesDetector,
    date_format_family,
)
from trusttable_backend.domain.observation import (
    MAX_OBSERVATION_ROW_REFERENCES,
    Observation,
    ObservationKind,
)
from trusttable_backend.domain.parsing import DatasetFormat, SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, RowReference
from trusttable_backend.exports.report_markdown import render_markdown
from trusttable_backend.exports.report_snapshot import ReportOptions, ReportVersions
from trusttable_backend.main import create_app
from trusttable_backend.persistence import SqlAnalysisStore, build_engine, run_migrations
from trusttable_backend.profiling.schemas import InferredColumnType
from trusttable_backend.profiling.type_inference import VALUE_SHAPES, classify_value_shape
from trusttable_backend.risk.scoring import (
    calculate_finding_priority_scores,
    calculate_trust_assessment,
)

MIXED_ID = "structural.mixed_types"
DATES_ID = "consistency.inconsistent_date_formats"
MISSING_ID = "completeness.concentrated_missingness"
NEW_IDS = frozenset({MIXED_ID, DATES_ID, MISSING_ID})
FIXED_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
SECRET = "TOPSECRET-VALUE-4711"


def make_request(
    *,
    names: tuple[str, ...],
    rows: tuple[Mapping[str, object], ...],
    inferred_type: InferredColumnType = InferredColumnType.CATEGORICAL,
    configuration: Mapping[str, object] | None = None,
    detector: object | None = None,
) -> DetectorRunRequest:
    profile = make_profile(names, row_count=len(rows), inferred_type=inferred_type)
    default_configuration = (
        dict(detector.metadata.default_configuration)  # type: ignore[attr-defined]
        if detector is not None
        else {}
    )
    return DetectorRunRequest(
        dataset_profile=profile,
        rows=rows,
        row_references=tuple(RowReference(row_number=index + 1) for index in range(len(rows))),
        confirmed_context=None,
        configuration={**default_configuration, **(configuration or {})},
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        security_exposure=NO_EXPOSURE,
    )


def column_rows(name: str, values: list[str | None]) -> tuple[Mapping[str, object], ...]:
    # `make_profile` keys columns by their name.
    return tuple({name: value} for value in values)


# ---------------------------------------------------------------------------
# The Observation type
# ---------------------------------------------------------------------------


def make_observation(**overrides: object) -> Observation:
    values: dict[str, object] = {
        "observation_id": "x.y.observation.1",
        "kind": ObservationKind.VALUE_EVIDENCE,
        "producer_detector_id": "x.y",
        "producer_version": "1",
        "summary": "A neutral statement.",
        "affected_columns": (),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "structured_payload": {"count": 1},
    }
    values.update(overrides)
    return Observation(**values)  # type: ignore[arg-type]


def test_an_observation_has_no_severity_confidence_or_priority() -> None:
    names = {field.name for field in dataclasses.fields(Observation)}
    assert names == {
        "observation_id",
        "kind",
        "producer_detector_id",
        "producer_version",
        "summary",
        "affected_columns",
        "affected_row_references",
        "scope",
        "structured_payload",
    }
    for forbidden in ("severity", "confidence", "priority", "score", "review", "dismissed"):
        assert not any(forbidden in name for name in names)


def test_there_is_exactly_one_observation_kind_today() -> None:
    assert [kind.value for kind in ObservationKind] == ["value_evidence"]


def test_an_observation_is_immutable_and_validates_its_invariants() -> None:
    observation = make_observation()
    with pytest.raises(dataclasses.FrozenInstanceError):
        observation.summary = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="observation_id"):
        make_observation(observation_id="")
    with pytest.raises(ValueError, match="namespaced"):
        make_observation(producer_detector_id="nodot")
    with pytest.raises(ValueError, match="summary"):
        make_observation(summary="")
    too_many = tuple(RowReference(row_number=n) for n in range(MAX_OBSERVATION_ROW_REFERENCES + 1))
    with pytest.raises(ValueError, match="bound"):
        make_observation(affected_row_references=too_many)


def test_a_failed_detector_result_cannot_carry_observations() -> None:
    with pytest.raises(ValueError, match="observations"):
        DetectorRunResult(
            detector_id="a.b",
            detector_version="1",
            status=DetectorRunStatus.FAILED,
            findings=(),
            evidence=(),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=0),
            safe_failure=SafeFailure(error_type="E", safe_message="failed"),
            observations=(make_observation(),),
        )


def test_a_result_defaults_to_no_observations() -> None:
    result = DetectorRunResult(
        detector_id="a.b",
        detector_version="1",
        status=DetectorRunStatus.SUCCESS,
        findings=(),
        evidence=(),
        warnings=(),
        execution_metrics=ExecutionMetrics(duration_ms=0),
    )
    assert result.observations == ()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_the_registry_holds_26_detectors_including_the_three_producers() -> None:
    ids = [detector.metadata.detector_id for detector in DETECTORS]
    assert len(ids) == 26
    assert len(set(ids)) == 26
    assert set(ids) >= NEW_IDS


def test_the_observation_only_set_is_exactly_the_three_producers() -> None:
    assert OBSERVATION_ONLY_DETECTOR_IDS == NEW_IDS


def test_producer_metadata_is_declared() -> None:
    for detector in (MixedTypesDetector(), InconsistentDateFormatsDetector()):
        assert detector.metadata.requires_raw_rows is True
        assert detector.metadata.requires_confirmed_context is False
        assert detector.metadata.requires_ingest_facts is False
    assert ConcentratedMissingnessDetector().metadata.requires_raw_rows is True
    assert MixedTypesDetector().metadata.applicable_inferred_types == (InferredColumnType.MIXED,)


# ---------------------------------------------------------------------------
# structural.mixed_types
# ---------------------------------------------------------------------------


def run_mixed(values: list[str | None], *, inferred_type: InferredColumnType) -> DetectorRunResult:
    return MixedTypesDetector().run(
        make_request(
            names=("v",),
            rows=column_rows("v", values),
            inferred_type=inferred_type,
            detector=MixedTypesDetector(),
        )
    )


def test_mixed_types_states_the_shape_counts_for_a_mixed_column() -> None:
    values: list[str | None] = ["1", "2", "3", "abc", "def", "true", None, ""]
    result = run_mixed(values, inferred_type=InferredColumnType.MIXED)

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()
    (observation,) = result.observations
    assert observation.kind is ObservationKind.VALUE_EVIDENCE
    assert observation.producer_detector_id == MIXED_ID
    assert observation.structured_payload == {
        "non_blank_count": 6,
        "shape_counts": {"boolean": 1, "numeric": 3, "text": 2},
        "dominant_shape": "numeric",
    }
    assert "6 non-blank value(s)" in observation.summary
    assert "3 numeric-like" in observation.summary
    # Example rows are the rows outside the dominant (numeric) shape, 1-based here.
    assert [r.row_number for r in observation.affected_row_references] == [4, 5, 6]


def test_mixed_types_is_silent_for_a_column_that_is_not_mixed() -> None:
    for inferred in (
        InferredColumnType.NUMERIC,
        InferredColumnType.TEXT,
        InferredColumnType.CATEGORICAL,
        InferredColumnType.UNKNOWN,
    ):
        assert run_mixed(["1", "abc"], inferred_type=inferred).observations == ()


def test_mixed_types_dominant_shape_ties_break_by_fixed_order() -> None:
    result = run_mixed(["true", "1", "x"], inferred_type=InferredColumnType.MIXED)
    (observation,) = result.observations
    assert observation.structured_payload["dominant_shape"] == "boolean"


def test_mixed_types_bounds_example_rows_and_keeps_exact_counts() -> None:
    values: list[str | None] = [*["1"] * 25, *["word"] * 30]
    (observation,) = run_mixed(values, inferred_type=InferredColumnType.MIXED).observations
    assert len(observation.affected_row_references) == MAX_OBSERVATION_ROW_REFERENCES
    payload = observation.structured_payload
    assert payload["shape_counts"] == {"numeric": 25, "text": 30}


def test_mixed_types_never_copies_a_cell_value() -> None:
    values: list[str | None] = ["1", "2", SECRET, "true"]
    (observation,) = run_mixed(values, inferred_type=InferredColumnType.MIXED).observations
    exposed = json.dumps(
        [observation.summary, dict(observation.structured_payload), observation.observation_id]
    )
    assert SECRET not in exposed


def test_mixed_types_is_repeatable_and_handles_no_rows() -> None:
    values: list[str | None] = ["1", "x", "true"]
    assert run_mixed(values, inferred_type=InferredColumnType.MIXED) == run_mixed(
        values, inferred_type=InferredColumnType.MIXED
    )
    assert run_mixed([], inferred_type=InferredColumnType.MIXED).observations == ()


def test_classify_value_shape_matches_the_profile_precedence() -> None:
    assert classify_value_shape("true") == "boolean"
    assert classify_value_shape("2024-01-31") == "date"
    assert classify_value_shape("12.5") == "numeric"
    assert classify_value_shape("hello") == "text"
    assert {classify_value_shape(v) for v in ("yes", "2024-02-02", "3", "z")} == set(VALUE_SHAPES)


# ---------------------------------------------------------------------------
# consistency.inconsistent_date_formats
# ---------------------------------------------------------------------------


def run_dates(values: list[str | None], **config: object) -> DetectorRunResult:
    return InconsistentDateFormatsDetector().run(
        make_request(
            names=("d",),
            rows=column_rows("d", values),
            configuration=config,
            detector=InconsistentDateFormatsDetector(),
        )
    )


@pytest.mark.parametrize(
    ("value", "family"),
    [
        ("2024-03-15", "iso_year_month_day"),
        ("2024/03/15", "slash_year_first"),
        ("15/03/2024", "slash_numeric"),
        ("03/15/2024", "slash_numeric"),
        ("15.03.2024", "dot_numeric"),
        ("15-03-2024", "dash_numeric"),
        ("15 March 2024", "day_month_name_year"),
        ("5 sept 2024", "day_month_name_year"),
        ("March 15, 2024", "month_name_day_year"),
        ("Mar 15 2024", "month_name_day_year"),
    ],
)
def test_each_recognised_date_format_family(value: str, family: str) -> None:
    assert date_format_family(value) == family
    assert family in DATE_FORMAT_FAMILIES


@pytest.mark.parametrize(
    "value",
    [
        "2024-13-01",
        "2024-02-30",
        "31/31/2024",
        "15 Marchh 2024",
        "March 32, 2024",
        "hello",
        "12345",
        "",
        "  ",
        "1" * 41,
        "2024-03-15T10:00:00",
    ],
)
def test_values_that_are_not_real_dates_have_no_family(value: str) -> None:
    assert date_format_family(value) is None


def test_inconsistent_date_formats_states_counts_per_family() -> None:
    values: list[str | None] = ["2024-01-05", "2024-01-06", "2024-01-07", "15/01/2024", None, ""]
    result = run_dates(values)

    assert result.findings == ()
    assert result.evidence == ()
    (observation,) = result.observations
    assert observation.kind is ObservationKind.VALUE_EVIDENCE
    assert observation.structured_payload["format_counts"] == {
        "iso_year_month_day": 3,
        "slash_numeric": 1,
    }
    assert observation.structured_payload["dominant_format"] == "iso_year_month_day"
    assert observation.structured_payload["date_like_count"] == 4
    assert observation.structured_payload["non_blank_count"] == 4
    assert [r.row_number for r in observation.affected_row_references] == [4]
    assert "2 different formats" in observation.summary


def test_a_single_format_is_silent() -> None:
    assert run_dates(["2024-01-05", "2024-02-06", "2024-03-07"]).observations == ()
    assert run_dates(["03/04/2024", "13/04/2024"]).observations == ()


def test_the_date_like_share_threshold_is_a_boundary() -> None:
    values: list[str | None] = ["2024-01-05", "05/01/2024", "alpha", "beta"]
    assert len(run_dates(values).observations) == 1  # 2 of 4 = 0.5 meets the default
    assert run_dates(values, minimum_date_like_ratio=0.51).observations == ()


def test_date_format_configuration_is_validated() -> None:
    schema = InconsistentDateFormatsDetector.config_schema
    for bad in (0.0, 1.5, float("nan"), "x"):
        with pytest.raises(ValidationError):
            schema.model_validate({"minimum_date_like_ratio": bad})
    with pytest.raises(ValidationError):
        schema.model_validate({"unknown": 1})


def test_date_observation_never_copies_a_cell_value() -> None:
    values: list[str | None] = ["2024-01-05", "05/01/2024", f"{SECRET}"]
    result = run_dates(values, minimum_date_like_ratio=0.1)
    exposed = json.dumps(
        [(o.summary, dict(o.structured_payload), o.observation_id) for o in result.observations]
    )
    assert SECRET not in exposed
    assert "2024-01-05" not in exposed
    assert "05/01/2024" not in exposed


def test_date_format_detector_is_repeatable_and_handles_no_rows() -> None:
    values: list[str | None] = ["2024-01-05", "05/01/2024"]
    assert run_dates(values) == run_dates(values)
    assert run_dates([]).observations == ()


# ---------------------------------------------------------------------------
# completeness.concentrated_missingness
# ---------------------------------------------------------------------------


def run_missing(values: list[str | None], **config: object) -> DetectorRunResult:
    return ConcentratedMissingnessDetector().run(
        make_request(
            names=("m", "k"),
            rows=tuple({"m": value, "k": "filled"} for value in values),
            configuration=config,
            detector=ConcentratedMissingnessDetector(),
        )
    )


def test_a_single_unbroken_run_of_missing_values_is_stated() -> None:
    values: list[str | None] = ["a"] * 5 + [None] * 10 + ["b"] * 5
    result = run_missing(values)

    assert result.findings == ()
    (observation,) = result.observations
    assert observation.kind is ObservationKind.VALUE_EVIDENCE
    payload = observation.structured_payload
    assert payload["missing_count"] == 10
    assert payload["longest_run_length"] == 10
    assert payload["run_share"] == 1.0
    assert payload["first_row_number"] == 6
    assert payload["last_row_number"] == 15
    assert payload["row_count"] == 20
    assert len(observation.affected_row_references) == 10


def test_scattered_missing_values_are_not_reported() -> None:
    values: list[str | None] = ["a", None] * 10
    assert run_missing(values).observations == ()


def test_a_run_below_the_minimum_length_is_not_reported() -> None:
    values: list[str | None] = ["a"] * 10 + [None] * 4 + ["b"] * 10
    assert run_missing(values).observations == ()
    assert len(run_missing(values, minimum_run_length=4).observations) == 1


def test_the_concentration_share_is_a_boundary() -> None:
    # A run of 8 plus 2 stray gaps: share 0.8 meets the default, 0.81 does not.
    values: list[str | None] = [None] * 8 + ["a"] * 5 + [None, "a", None] + ["a"] * 5
    assert len(run_missing(values).observations) == 1
    assert run_missing(values, concentration_ratio=0.81).observations == ()


def test_a_run_is_measured_over_the_longest_run_only() -> None:
    values: list[str | None] = [None] * 6 + ["a"] * 3 + [None] * 6 + ["a"] * 3
    # Two runs of 6 of 12: share 0.5, below the default 0.8.
    assert run_missing(values).observations == ()


def test_a_column_with_no_value_at_all_is_skipped() -> None:
    values: list[str | None] = [None] * 12
    result = ConcentratedMissingnessDetector().run(
        make_request(
            names=("m", "k"),
            rows=tuple({"m": None, "k": "filled"} for _ in values),
            detector=ConcentratedMissingnessDetector(),
        )
    )
    assert result.observations == ()


def test_rows_blank_in_every_column_are_excluded_first() -> None:
    rows: tuple[Mapping[str, object], ...] = tuple(
        [{"m": "a", "k": "x"}] * 6
        + [{"m": None, "k": None}] * 8  # trailing blank lines: not a block in every column
        + [{"m": "a", "k": "x"}] * 6
    )
    result = ConcentratedMissingnessDetector().run(
        make_request(names=("m", "k"), rows=rows, detector=ConcentratedMissingnessDetector())
    )
    assert result.observations == ()


def test_missingness_configuration_is_validated() -> None:
    schema = ConcentratedMissingnessDetector.config_schema
    schema.model_validate({"minimum_run_length": 2, "concentration_ratio": 1.0})
    for bad in (
        {"minimum_run_length": 1},
        {"concentration_ratio": 0.0},
        {"concentration_ratio": 2},
    ):
        with pytest.raises(ValidationError):
            schema.model_validate(bad)
    with pytest.raises(ValidationError):
        schema.model_validate({"surprise": True})


def test_missingness_is_repeatable_and_handles_no_rows() -> None:
    values: list[str | None] = ["a"] * 5 + [None] * 10 + ["b"] * 5
    assert run_missing(values) == run_missing(values)
    assert run_missing([]).observations == ()


def test_missingness_never_copies_a_cell_value() -> None:
    values: list[str | None] = [SECRET] * 5 + [None] * 10 + [SECRET] * 5
    (observation,) = run_missing(values).observations
    exposed = json.dumps(
        [observation.summary, dict(observation.structured_payload), observation.observation_id]
    )
    assert SECRET not in exposed


# ---------------------------------------------------------------------------
# End to end: real parsers, the live pipeline, the persisted store and the API
# ---------------------------------------------------------------------------


def sample_csv() -> bytes:
    lines = ["id,mixed,when,note"]
    for i in range(1, 31):
        mixed = str(i) if i % 3 else "n/a"
        when = f"2024-01-{(i % 28) + 1:02d}" if i <= 20 else f"{(i % 12) + 1:02d}/15/2024"
        note = "" if 8 <= i <= 22 else "x"
        lines.append(f"{i},{mixed},{when},{note}")
    return ("\n".join(lines) + "\n").encode()


def run_csv(content: bytes) -> Analysis:
    store = AnalysisStore()
    created = create_analysis_from_upload(store, content=content, original_filename="x.csv")
    return run_analysis(store, created.analysis_id, now=FIXED_NOW)


def observations_by_detector(analysis: Analysis) -> dict[str, list[Observation]]:
    grouped: dict[str, list[Observation]] = {}
    for observation in analysis.observations:
        grouped.setdefault(observation.producer_detector_id, []).append(observation)
    return grouped


def test_the_live_pipeline_collects_observations_beside_the_findings() -> None:
    analysis = run_csv(sample_csv())

    assert analysis.state is AnalysisState.COMPLETED
    grouped = observations_by_detector(analysis)
    assert {o.affected_columns[0].original_name for o in grouped[MIXED_ID]} >= {"mixed"}
    assert {o.affected_columns[0].original_name for o in grouped[DATES_ID]} == {"when"}
    assert {o.affected_columns[0].original_name for o in grouped[MISSING_ID]} == {"note"}
    # No finding comes from a producer.
    assert NEW_IDS.isdisjoint({finding.detector_id for finding in analysis.findings})


def test_a_header_only_file_and_a_clean_file_have_no_observations() -> None:
    assert run_csv(b"a,b\n").observations == ()
    assert run_csv(b"a,b\n1,2\n3,4\n").observations == ()


def test_observations_are_empty_unless_the_analysis_completed() -> None:
    store = AnalysisStore()
    created = create_analysis_from_upload(store, content=b"a\n1\n", original_filename="x.csv")
    with pytest.raises(ValueError, match="observations must be empty"):
        dataclasses.replace(created, observations=(make_observation(),))


def test_xlsx_runs_the_same_producers() -> None:
    from tests.parsers.test_xlsx_parser import build_xlsx

    rows: list[list[str | None]] = [["when", "n"]]
    rows += [[f"2024-01-{i:02d}", "x"] for i in range(1, 6)]
    rows += [[f"{i:02d}/15/2024", "x"] for i in range(1, 6)]
    store = AnalysisStore()
    created = create_analysis_from_upload(
        store,
        content=build_xlsx({"Sheet1": rows}),
        original_filename="x.xlsx",
        dataset_format=DatasetFormat.XLSX,
        selected_worksheet="Sheet1",
    )
    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)
    assert completed.state is AnalysisState.COMPLETED
    assert DATES_ID in observations_by_detector(completed)


def test_the_new_producers_do_not_change_findings_priority_or_trust_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = sample_csv()
    with_producers = run_csv(content)

    without = tuple(d for d in DETECTORS if d.metadata.detector_id not in NEW_IDS)
    assert len(without) == 23
    monkeypatch.setattr(analysis_service, "DETECTORS", without)
    baseline = run_csv(content)

    assert with_producers.observations
    assert baseline.observations == ()
    assert with_producers.findings == baseline.findings
    assert with_producers.priority_scores == baseline.priority_scores
    assert with_producers.trust_assessment == baseline.trust_assessment
    assert with_producers.evidence == baseline.evidence


def test_the_demo_dataset_score_is_unchanged_apart_from_the_new_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run_demo() -> Analysis:
        store = AnalysisStore()
        created = analysis_service.create_analysis(store)
        return run_analysis(store, created.analysis_id, now=FIXED_NOW)

    with_producers = run_demo()
    monkeypatch.setattr(
        analysis_service,
        "DETECTORS",
        tuple(d for d in DETECTORS if d.metadata.detector_id not in NEW_IDS),
    )
    baseline = run_demo()

    assert with_producers.findings == baseline.findings
    assert with_producers.priority_scores == baseline.priority_scores
    assert with_producers.trust_assessment == baseline.trust_assessment


def test_observations_round_trip_through_the_sql_store(tmp_path: Path) -> None:
    from trusttable_backend.config import get_settings

    settings = get_settings()
    run_migrations(settings)
    store = SqlAnalysisStore(build_engine(settings))
    created = create_analysis_from_upload(store, content=sample_csv(), original_filename="x.csv")
    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    loaded = store.get(created.analysis_id)

    assert loaded is not None
    assert completed.observations
    assert loaded.observations == completed.observations


def test_a_row_written_before_the_column_existed_reads_as_no_observations() -> None:
    from sqlalchemy import update

    from trusttable_backend.config import get_settings
    from trusttable_backend.persistence.models import AnalysisRecord

    settings = get_settings()
    run_migrations(settings)
    engine = build_engine(settings)
    store = SqlAnalysisStore(engine)
    created = create_analysis_from_upload(store, content=sample_csv(), original_filename="x.csv")
    run_analysis(store, created.analysis_id, now=FIXED_NOW)
    with store._session_factory() as session:  # noqa: SLF001 - simulate a pre-0008 row
        session.execute(update(AnalysisRecord).values(observations_json=None))
        session.commit()

    loaded = store.get(created.analysis_id)

    assert loaded is not None
    assert loaded.state is AnalysisState.COMPLETED
    assert loaded.observations == ()


def wait_for_terminal(client: TestClient, analysis_id: str) -> None:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state in {"completed", "failed", "cancelled"}:
            return
        time.sleep(0.01)
    raise AssertionError("analysis did not reach a terminal state")


def test_the_observations_route_is_read_only_and_neutral() -> None:
    with TestClient(create_app()) as client:
        created = client.post(
            "/api/v1/analyses", files={"file": ("x.csv", sample_csv(), "text/csv")}
        )
        assert created.status_code == 202
        analysis_id = created.json()["analysis"]["analysis_id"]
        wait_for_terminal(client, analysis_id)

        response = client.get(f"/api/v1/analyses/{analysis_id}/observations")
        assert response.status_code == 200
        body = response.json()
        assert body["total_items"] == len(body["items"]) > 0
        for item in body["items"]:
            assert set(item) == {
                "observation_id",
                "kind",
                "producer_detector_id",
                "summary",
                "affected_columns",
                "affected_row_numbers",
                "scope",
            }
            assert item["kind"] == "value_evidence"
            assert len(item["affected_row_numbers"]) <= MAX_OBSERVATION_ROW_REFERENCES
        # The trust assessment is untouched by observations: same body twice.
        resource = client.get(f"/api/v1/analyses/{analysis_id}").json()
        assert "observations" not in json.dumps(resource)

        for method in (client.post, client.put, client.delete, client.patch):
            assert method(f"/api/v1/analyses/{analysis_id}/observations").status_code == 405

        assert client.get("/api/v1/analyses/missing/observations").status_code == 404


def test_the_observations_route_is_empty_for_a_queued_analysis() -> None:
    from trusttable_backend.analysis.service import create_analysis_from_upload as create

    with TestClient(create_app()) as client:
        store = client.app.state.analysis_store  # type: ignore[attr-defined]
        queued = create(store, content=b"a\n1\n", original_filename="q.csv")
        response = client.get(f"/api/v1/analyses/{queued.analysis_id}/observations")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total_items": 0}


# ---------------------------------------------------------------------------
# Negative allowlist: an Observation never reaches score, priority, an AI
# payload, an export or a report
# ---------------------------------------------------------------------------

_SRC_ROOT = Path(trusttable_backend.__file__).resolve().parent
_OBSERVATION_REFERENCE = re.compile(
    r"\bObservation\b|\bObservationKind\b|domain\.observation|\.observations\b|\bobservations\s*[=:]"
)

#: Every source module allowed to mention the Observation type or the
#: `observations` field. A module outside this set that starts to mention one
#: fails this test: scoring, priority, guidance, rules, exports, reports and the
#: AI boundary are deliberately not in it.
_ALLOWED_OBSERVATION_MODULES = frozenset(
    {
        "analysis/service.py",
        "api/v1/analyses.py",
        "detectors/contract.py",
        "detectors/value_evidence.py",
        "domain/observation.py",
        "persistence/store.py",
        "schemas/analysis.py",
    }
)


def test_only_allowlisted_modules_reference_observations() -> None:
    referencing = {
        path.relative_to(_SRC_ROOT).as_posix()
        for path in _SRC_ROOT.rglob("*.py")
        if _OBSERVATION_REFERENCE.search(path.read_text(encoding="utf-8"))
    }
    assert referencing == _ALLOWED_OBSERVATION_MODULES


@pytest.mark.parametrize(
    "module",
    [
        "risk/scoring.py",
        "exports/report_markdown.py",
        "exports/report_snapshot.py",
        "ai_boundary/envelope.py",
        "ai_boundary/prompt.py",
        "ai_provider/contract.py",
        "explanation/ai_explanation.py",
        "explanation/guidance.py",
        "context_inference/ai_context.py",
        "rules/ai_generation.py",
        "rules/generation.py",
        "api/v1/reports.py",
        "schemas/report.py",
    ],
)
def test_scoring_guidance_rules_exports_reports_and_ai_never_mention_observations(
    module: str,
) -> None:
    path = _SRC_ROOT / module
    assert path.exists(), module
    assert _OBSERVATION_REFERENCE.search(path.read_text(encoding="utf-8")) is None


def test_scoring_and_priority_take_no_observation_input() -> None:
    import inspect

    for function in (calculate_finding_priority_scores, calculate_trust_assessment):
        assert "observation" not in " ".join(inspect.signature(function).parameters)


def test_injected_observations_change_neither_the_score_nor_the_report() -> None:
    analysis = run_csv(sample_csv())
    sentinel = make_observation(
        observation_id="sentinel.observation.1",
        producer_detector_id="sentinel.producer",
        summary="SENTINEL-OBSERVATION-SUMMARY",
        affected_columns=(
            ColumnReference(original_name="SENTINEL-COLUMN", internal_key="s", ordinal=99),
        ),
        structured_payload={"marker": "SENTINEL-OBSERVATION-PAYLOAD"},
    )
    injected = dataclasses.replace(analysis, observations=(sentinel, *analysis.observations))

    assert injected.trust_assessment == analysis.trust_assessment
    assert injected.dataset_profile is not None
    recomputed = calculate_trust_assessment(
        injected.findings,
        calculate_finding_priority_scores(
            injected.findings, dataset_profile=injected.dataset_profile
        ),
        security_exposure=injected.security_exposure,
    )
    assert recomputed == analysis.trust_assessment

    versions = ReportVersions(application_version="0")
    for options in (
        ReportOptions(),
        ReportOptions(True, True, True),
    ):
        base = render_markdown(analysis, options=options, versions=versions, ai_enrichment=None)
        with_obs = render_markdown(injected, options=options, versions=versions, ai_enrichment=None)
        assert with_obs == base
        assert "SENTINEL-OBSERVATION" not in with_obs
        assert "SENTINEL-COLUMN" not in with_obs
