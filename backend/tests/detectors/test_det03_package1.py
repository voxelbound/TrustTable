"""Tests for `DET-03` closure package 1 (D-061): the zero-row investigation,
the in-memory ingest-facts projection, and the detectors
`structural.empty_dataset`, `structural.unnamed_column` and
`structural.excessive_parse_failures`.

Follows `docs/detector-framework.md` §15's detector test contract (positive,
negative, threshold boundary, empty and malformed input, repeatability,
configuration and known false positives). Two properties matter most and are
pinned against the real parsers rather than hand-built facts:

- the projection never carries a parser message or a cell value, and never
  carries processing-limit truncation;
- a detector that needs ingest facts is skipped, never run and never passed,
  when none are supplied.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tests.detectors.test_det03_slice1 import (
    ANALYSIS_TIMESTAMP,
    NO_EXPOSURE,
    make_profile,
)
from tests.parsers.test_xlsx_parser import Cell, build_xlsx
from trusttable_backend.analysis.service import (
    AnalysisState,
    AnalysisStore,
    create_analysis_from_upload,
    run_analysis,
)
from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    Detector,
    DetectorCategory,
    DetectorMetadata,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    DetectorSupportRequest,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.detectors.structural import (
    EmptyDatasetDetector,
    ExcessiveParseFailuresDetector,
    UnnamedColumnDetector,
)
from trusttable_backend.domain.evidence import EvidenceType
from trusttable_backend.domain.ingest_facts import (
    INGEST_FACT_WARNING_CODES,
    MAX_REFERENCES,
    IngestFacts,
    project_ingest_facts,
)
from trusttable_backend.domain.parsing import (
    DatasetFormat,
    ParsedDataset,
    ParsingWarning,
    SampleMetadata,
    SamplingScope,
)
from trusttable_backend.domain.value_objects import ColumnReference, RowReference, Severity
from trusttable_backend.parsers.csv_parser import CsvParseError, CsvParseLimits, parse_csv
from trusttable_backend.parsers.xlsx_parser import XlsxParseError, parse_xlsx
from trusttable_backend.profiling.metrics import compute_dataset_profile

EMPTY_ID = "structural.empty_dataset"
UNNAMED_ID = "structural.unnamed_column"
EXCESSIVE_ID = "structural.excessive_parse_failures"
FIXED_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

DEFAULT_CONFIG = ExcessiveParseFailuresDetector.metadata.default_configuration


def facts(
    *,
    row_count: int = 100,
    column_count: int = 4,
    unnamed: tuple[int, ...] = (),
    unnamed_count: int | None = None,
    ragged_rows: tuple[int, ...] = (),
    ragged_count: int | None = None,
    formula_cells: int = 0,
    error_cells: int = 0,
) -> IngestFacts:
    return IngestFacts(
        row_count=row_count,
        column_count=column_count,
        unnamed_column_count=len(unnamed) if unnamed_count is None else unnamed_count,
        unnamed_columns=tuple(
            ColumnReference(original_name=f"column_{n}", internal_key=f"column_{n}", ordinal=n)
            for n in unnamed
        ),
        ragged_row_count=len(ragged_rows) if ragged_count is None else ragged_count,
        ragged_rows=tuple(RowReference(row_number=n) for n in ragged_rows),
        formula_without_cached_value_cell_count=formula_cells,
        error_value_cell_count=error_cells,
    )


def request(
    ingest_facts: IngestFacts | None,
    *,
    row_count: int = 100,
    names: tuple[str, ...] = ("a", "b", "c", "d"),
    configuration: dict[str, object] | None = None,
) -> DetectorRunRequest:
    return DetectorRunRequest(
        dataset_profile=make_profile(names, row_count=row_count),
        rows=(),
        row_references=(),
        confirmed_context=None,
        configuration=DEFAULT_CONFIG if configuration is None else configuration,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        security_exposure=NO_EXPOSURE,
        ingest_facts=ingest_facts,
    )


def run_excessive(ingest_facts: IngestFacts | None, **config: object) -> DetectorRunResult:
    return ExcessiveParseFailuresDetector().run(
        request(ingest_facts, configuration={**DEFAULT_CONFIG, **config})
    )


def evidence_text(result: DetectorRunResult) -> str:
    """Everything a result exposes, as one string, for leak checks."""
    return json.dumps(
        [
            [
                finding.calculated_observation,
                [(c.original_name, c.internal_key) for c in finding.affected_columns],
            ]
            for finding in result.findings
        ]
        + [[item.display_safe_summary, dict(item.structured_payload)] for item in result.evidence],
        default=str,
    )


# ---------------------------------------------------------------------------
# Zero-row and header-only investigation: detector execution owns the case
# ---------------------------------------------------------------------------


def test_header_only_csv_is_accepted_by_the_parser_with_no_warning() -> None:
    """The parser does not own the case: a header-only CSV parses to zero rows."""
    parsed = parse_csv(b"a,b,c\n")
    assert parsed.parsed_dataset.row_count == 0
    assert parsed.rows == ()
    assert parsed.parsed_dataset.parsing_warnings == ()


def test_header_only_xlsx_is_accepted_by_the_parser_with_no_warning() -> None:
    parsed = parse_xlsx(build_xlsx({"Sheet1": [["a", "b", "c"]]}), worksheet="Sheet1")
    assert parsed.parsed_dataset.row_count == 0
    assert parsed.rows == ()
    assert parsed.parsed_dataset.parsing_warnings == ()


@pytest.mark.parametrize("content", [b"", b"\n"])
def test_content_with_no_header_row_is_refused_by_the_parser_before_detection(
    content: bytes,
) -> None:
    """Only truly empty content is parser-owned; it never reaches a detector."""
    with pytest.raises(CsvParseError):
        parse_csv(content)


def test_a_worksheet_with_no_header_row_is_refused_by_the_parser_before_detection() -> None:
    with pytest.raises(XlsxParseError):
        parse_xlsx(build_xlsx({"Sheet1": []}), worksheet="Sheet1")


def test_header_only_csv_completes_the_analysis_with_one_dataset_level_finding() -> None:
    store = AnalysisStore()
    created = create_analysis_from_upload(store, content=b"a,b,c\n", original_filename="empty.csv")

    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert completed.state is AnalysisState.COMPLETED
    ids = [finding.detector_id for finding in completed.findings]
    assert ids.count(EMPTY_ID) == 1
    (finding,) = [f for f in completed.findings if f.detector_id == EMPTY_ID]
    assert finding.severity is Severity.HIGH
    assert "no data rows" in finding.calculated_observation
    assert completed.trust_assessment is not None


def test_header_only_xlsx_completes_the_analysis_with_the_same_finding() -> None:
    store = AnalysisStore()
    created = create_analysis_from_upload(
        store,
        content=build_xlsx({"Sheet1": [["a", "b", "c"]]}),
        original_filename="empty.xlsx",
        dataset_format=DatasetFormat.XLSX,
        selected_worksheet="Sheet1",
    )

    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert completed.state is AnalysisState.COMPLETED
    assert [f.detector_id for f in completed.findings].count(EMPTY_ID) == 1


def test_a_dataset_with_rows_never_gets_the_empty_dataset_finding() -> None:
    store = AnalysisStore()
    created = create_analysis_from_upload(store, content=b"a,b\n1,2\n", original_filename="one.csv")

    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert EMPTY_ID not in {f.detector_id for f in completed.findings}


# ---------------------------------------------------------------------------
# structural.empty_dataset
# ---------------------------------------------------------------------------


def test_empty_dataset_metadata_and_config() -> None:
    detector = EmptyDatasetDetector()
    assert detector.metadata.detector_id == EMPTY_ID
    assert detector.metadata.category is DetectorCategory.STRUCTURAL
    assert detector.metadata.requires_raw_rows is False
    assert detector.metadata.requires_ingest_facts is False
    detector.config_schema.model_validate({})


def test_empty_dataset_flags_zero_rows_with_one_finding_and_metric_evidence() -> None:
    result = EmptyDatasetDetector().run(request(None, row_count=0, names=("a", "b", "c")))

    assert result.status is DetectorRunStatus.SUCCESS
    (finding,) = result.findings
    (evidence,) = result.evidence
    assert finding.severity is Severity.HIGH
    assert finding.confidence == 1.0
    assert finding.evidence_ids == (evidence.evidence_id,)
    assert evidence.evidence_type is EvidenceType.METRIC
    assert evidence.structured_payload == {"row_count": 0, "column_count": 3}
    assert finding.affected_columns == () and finding.affected_row_references == ()


@pytest.mark.parametrize("rows", [1, 2, 1000])
def test_empty_dataset_does_not_flag_any_dataset_with_rows(rows: int) -> None:
    result = EmptyDatasetDetector().run(request(None, row_count=rows))
    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == () and result.evidence == ()


def test_empty_dataset_boundary_one_row_versus_zero_rows() -> None:
    assert EmptyDatasetDetector().run(request(None, row_count=1)).findings == ()
    assert len(EmptyDatasetDetector().run(request(None, row_count=0)).findings) == 1


def test_empty_dataset_ignores_a_malformed_row_count_metric_and_uses_the_sampling_population() -> (
    None
):
    profile = make_profile(("a",), row_count=0)
    for bad in (True, "0", None, 2.5):
        malformed = dataclasses.replace(profile, dataset_metrics={"row_count": bad})
        run = dataclasses.replace(request(None, row_count=0), dataset_profile=malformed)
        # `True` is an int subclass and must not be read as a count of one row.
        assert len(EmptyDatasetDetector().run(run).findings) == 1


def test_empty_dataset_is_repeatable() -> None:
    first = EmptyDatasetDetector().run(request(None, row_count=0))
    second = EmptyDatasetDetector().run(request(None, row_count=0))
    assert first == second


def test_empty_dataset_reads_no_cell_and_no_ingest_facts() -> None:
    run = request(facts(row_count=50, ragged_rows=(1,)), row_count=0)
    result = EmptyDatasetDetector().run(run)
    assert len(result.findings) == 1


# ---------------------------------------------------------------------------
# The ingest-facts projection
# ---------------------------------------------------------------------------


def test_the_projection_reads_exactly_four_parser_warning_codes() -> None:
    expected = frozenset(
        {
            "parsing.empty_column_name",
            "parsing.ragged_row",
            "parsing.xlsx_formula_without_cached_value",
            "parsing.xlsx_error_value",
        }
    )
    assert expected == INGEST_FACT_WARNING_CODES


def test_the_projection_is_immutable() -> None:
    projected = facts(unnamed=(1,), ragged_rows=(2,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        projected.row_count = 5  # type: ignore[misc]
    assert isinstance(projected.unnamed_columns, tuple)
    assert isinstance(projected.ragged_rows, tuple)
    with pytest.raises((AttributeError, TypeError)):
        projected.extra = 1  # type: ignore[attr-defined]


def test_the_projection_has_no_message_or_value_fields() -> None:
    names = {field.name for field in dataclasses.fields(IngestFacts)}
    assert names == {
        "row_count",
        "column_count",
        "unnamed_column_count",
        "unnamed_columns",
        "ragged_row_count",
        "ragged_rows",
        "formula_without_cached_value_cell_count",
        "error_value_cell_count",
    }


def test_the_projection_rejects_negative_counts_and_unbounded_references() -> None:
    with pytest.raises(ValueError):
        facts(row_count=-1)
    with pytest.raises(ValueError):
        facts(formula_cells=-1)
    with pytest.raises(ValueError):
        facts(unnamed=(0, 1), unnamed_count=1)  # more references than the count
    with pytest.raises(ValueError):
        facts(ragged_rows=tuple(range(MAX_REFERENCES + 1)), ragged_count=MAX_REFERENCES + 1)


def test_the_projection_of_a_csv_with_blank_and_ragged_headers_and_rows() -> None:
    parsed = parse_csv(b"a,,c,\n1,2,3,4\n1,2\n1,2,3,4,5\n1,2,3,4\n")

    projected = project_ingest_facts(parsed.parsed_dataset)

    assert projected.row_count == 4
    assert projected.column_count == 4
    assert projected.unnamed_column_count == 2
    assert [c.ordinal for c in projected.unnamed_columns] == [1, 3]
    assert [c.original_name for c in projected.unnamed_columns] == ["column_1", "column_3"]
    assert projected.ragged_row_count == 2
    assert [r.row_number for r in projected.ragged_rows] == [1, 2]
    assert projected.formula_without_cached_value_cell_count == 0
    assert projected.error_value_cell_count == 0


def test_the_projection_of_a_clean_csv_is_all_zero() -> None:
    projected = project_ingest_facts(parse_csv(b"a,b\n1,2\n3,4\n").parsed_dataset)
    assert (projected.unnamed_column_count, projected.ragged_row_count) == (0, 0)
    assert projected.unnamed_columns == () and projected.ragged_rows == ()


def test_the_projection_of_an_xlsx_carries_structured_cell_counts() -> None:
    content = build_xlsx(
        {
            "Sheet1": [
                ["a", None, "c"],
                [("formula", "1+1", None), ("formula", "2+2", None), ("error", "#REF!")],
                [("formula", "3+3", 6), ("error", "#N/A"), ("error", "#DIV/0!")],
            ]
        }
    )
    parsed = parse_xlsx(content, worksheet="Sheet1")

    projected = project_ingest_facts(parsed.parsed_dataset)

    assert projected.formula_without_cached_value_cell_count == 2
    assert projected.error_value_cell_count == 3
    assert projected.unnamed_column_count == 1


def test_the_projection_counts_come_from_the_structured_count_not_the_message() -> None:
    columns = (ColumnReference(original_name="a", internal_key="a", ordinal=0),)
    dataset = ParsedDataset(
        columns=columns,
        row_count=1,
        format=DatasetFormat.CSV,
        worksheets=(),
        parsing_warnings=(
            ParsingWarning(
                code="parsing.xlsx_error_value",
                message="999 cell(s) held a spreadsheet error value",
                count=7,
            ),
        ),
        sampling=SampleMetadata(scope=SamplingScope.FULL, population_size=1, sample_size=1),
        row_references=(RowReference(row_number=0),),
    )
    assert project_ingest_facts(dataset).error_value_cell_count == 7


def test_the_projection_excludes_processing_limit_truncation_and_other_codes() -> None:
    """Long values and long names are truncated by a TrustTable limit. That is not
    a defect in the user's data, so it must not reach any ingest-fact detector."""
    limits = CsvParseLimits(max_field_length=5, max_column_name_length=4)
    parsed = parse_csv(b"abcdefgh,b\n" + b"x" * 40 + b",1\n" + b"y" * 40 + b",2\n", limits=limits)
    codes = {w.code for w in parsed.parsed_dataset.parsing_warnings}
    assert "parsing.field_value_truncated" in codes
    assert "parsing.column_name_truncated" in codes

    projected = project_ingest_facts(parsed.parsed_dataset)

    assert (projected.unnamed_column_count, projected.ragged_row_count) == (0, 0)
    assert projected.formula_without_cached_value_cell_count == 0
    assert projected.error_value_cell_count == 0
    assert run_excessive(projected, minimum_count=1).findings == ()


def test_the_projection_drops_row_fingerprints_and_source_lines() -> None:
    dataset = ParsedDataset(
        columns=(ColumnReference(original_name="a", internal_key="a", ordinal=0),),
        row_count=3,
        format=DatasetFormat.CSV,
        worksheets=(),
        parsing_warnings=(
            ParsingWarning(
                code="parsing.ragged_row",
                message="Row 1 had 2 fields",
                row=RowReference(row_number=1, source_line_number=9, fingerprint="deadbeef"),
            ),
        ),
        sampling=SampleMetadata(scope=SamplingScope.FULL, population_size=3, sample_size=3),
        row_references=tuple(RowReference(row_number=i) for i in range(3)),
    )
    (reference,) = project_ingest_facts(dataset).ragged_rows
    assert reference == RowReference(row_number=1)
    assert reference.fingerprint is None and reference.source_line_number is None


def test_the_projection_bounds_references_but_keeps_exact_counts() -> None:
    body = b"a,b\n" + b"1\n" * 500
    projected = project_ingest_facts(parse_csv(body).parsed_dataset)
    assert projected.ragged_row_count == 500
    assert len(projected.ragged_rows) == MAX_REFERENCES
    assert [r.row_number for r in projected.ragged_rows] == list(range(MAX_REFERENCES))


def test_the_projection_orders_and_deduplicates_references_deterministically() -> None:
    column = ColumnReference(original_name="column_3", internal_key="column_3", ordinal=3)
    dataset = ParsedDataset(
        columns=(
            ColumnReference(original_name="column_1", internal_key="column_1", ordinal=1),
            column,
        ),
        row_count=0,
        format=DatasetFormat.CSV,
        worksheets=(),
        parsing_warnings=(
            ParsingWarning(code="parsing.empty_column_name", message="m", column=column),
            ParsingWarning(
                code="parsing.empty_column_name",
                message="m",
                column=ColumnReference(
                    original_name="column_1", internal_key="column_1", ordinal=1
                ),
            ),
            ParsingWarning(code="parsing.empty_column_name", message="m", column=column),
        ),
        sampling=SampleMetadata(scope=SamplingScope.FULL, population_size=0, sample_size=0),
        row_references=(),
    )
    first = project_ingest_facts(dataset)
    assert [c.ordinal for c in first.unnamed_columns] == [1, 3]
    assert first.unnamed_column_count == 3  # the count is of warnings, never deduplicated
    assert project_ingest_facts(dataset) == first


def test_a_parsing_warning_count_must_be_positive_and_defaults_to_one() -> None:
    assert ParsingWarning(code="parsing.x", message="m").count == 1
    with pytest.raises(ValueError):
        ParsingWarning(code="parsing.x", message="m", count=0)


# ---------------------------------------------------------------------------
# Engine: the metadata flag defaults off and absent facts mean skipped
# ---------------------------------------------------------------------------


def _engine(
    ingest_facts: IngestFacts | None, detectors: Sequence[Detector]
) -> tuple[DetectorRunResult, ...]:
    return run_detectors(
        detectors,
        dataset_profile=make_profile(("a", "b"), row_count=3),
        rows=(),
        row_references=(),
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        ingest_facts=ingest_facts,
    )


def test_the_metadata_flag_defaults_to_off_for_every_pre_existing_detector() -> None:
    flagged = {d.metadata.detector_id for d in DETECTORS if d.metadata.requires_ingest_facts}
    assert flagged == {UNNAMED_ID, EXCESSIVE_ID}
    assert DetectorMetadata.__dataclass_fields__["requires_ingest_facts"].default is False


def test_a_detector_that_requires_facts_is_skipped_when_none_are_supplied() -> None:
    results = _engine(None, [UnnamedColumnDetector(), ExcessiveParseFailuresDetector()])
    for result in results:
        assert result.status is DetectorRunStatus.SKIPPED
        assert result.findings == () and result.evidence == ()
        assert [w.code for w in result.warnings] == ["detector.skipped_ingest_facts_absent"]


def test_a_detector_that_requires_facts_receives_them_when_supplied() -> None:
    results = _engine(facts(unnamed=(2,)), [UnnamedColumnDetector()])
    (result,) = results
    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1


def test_a_detector_that_does_not_require_facts_is_never_passed_them() -> None:
    seen: list[IngestFacts | None] = []

    class Recorder:
        metadata = dataclasses.replace(
            EmptyDatasetDetector.metadata, detector_id="structural.recorder"
        )
        config_schema = EmptyDatasetDetector.config_schema

        def supports(self, request: DetectorSupportRequest) -> bool:
            seen.append(request.ingest_facts)
            return True

        def run(self, request: DetectorRunRequest) -> DetectorRunResult:
            seen.append(request.ingest_facts)
            return EmptyDatasetDetector().run(request)

    _engine(facts(unnamed=(0,)), [Recorder()])

    assert seen == [None, None]


def test_the_engine_does_not_require_facts_for_the_original_detectors() -> None:
    originals = [d for d in DETECTORS if not d.metadata.requires_ingest_facts]
    results = _engine(None, originals)
    skipped_for_facts = [
        r.detector_id
        for r in results
        if any(w.code == "detector.skipped_ingest_facts_absent" for w in r.warnings)
    ]
    assert skipped_for_facts == []


def test_supports_is_false_without_facts_even_if_called_directly() -> None:
    support = DetectorSupportRequest(
        dataset_profile=make_profile(("a",), row_count=1),
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
    )
    assert UnnamedColumnDetector().supports(support) is False
    assert ExcessiveParseFailuresDetector().supports(support) is False
    with_facts = dataclasses.replace(support, ingest_facts=facts())
    assert UnnamedColumnDetector().supports(with_facts) is True
    assert ExcessiveParseFailuresDetector().supports(with_facts) is True


# ---------------------------------------------------------------------------
# structural.unnamed_column
# ---------------------------------------------------------------------------


def test_unnamed_column_metadata_and_config() -> None:
    detector = UnnamedColumnDetector()
    assert detector.metadata.detector_id == UNNAMED_ID
    assert detector.metadata.category is DetectorCategory.STRUCTURAL
    assert detector.metadata.requires_ingest_facts is True
    assert detector.metadata.requires_raw_rows is False
    detector.config_schema.model_validate({})


def test_unnamed_column_flags_blank_headers_with_one_finding() -> None:
    result = UnnamedColumnDetector().run(request(facts(unnamed=(1, 3), column_count=4)))

    assert result.status is DetectorRunStatus.SUCCESS
    (finding,) = result.findings
    (evidence,) = result.evidence
    assert finding.severity is Severity.MEDIUM
    assert [c.ordinal for c in finding.affected_columns] == [1, 3]
    assert evidence.structured_payload == {
        "unnamed_column_count": 2,
        "column_count": 4,
        "ordinals": [1, 3],
    }
    assert "2 of 4" in finding.calculated_observation


def test_unnamed_column_is_silent_for_fully_named_headers() -> None:
    result = UnnamedColumnDetector().run(request(facts()))
    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == () and result.evidence == ()


def test_unnamed_column_boundary_one_blank_header_is_enough() -> None:
    assert len(UnnamedColumnDetector().run(request(facts(unnamed=(0,)))).findings) == 1


def test_unnamed_column_reports_the_exact_count_when_references_are_capped() -> None:
    shown = tuple(range(MAX_REFERENCES))
    result = UnnamedColumnDetector().run(
        request(facts(unnamed=shown, unnamed_count=300, column_count=300))
    )
    (finding,) = result.findings
    assert len(finding.affected_columns) == MAX_REFERENCES
    assert "300 of 300" in finding.calculated_observation
    assert "more" in finding.calculated_observation
    assert result.evidence[0].structured_payload["unnamed_column_count"] == 300


def test_unnamed_column_without_facts_produces_nothing_when_run_directly() -> None:
    result = UnnamedColumnDetector().run(request(None))
    assert result.findings == () and result.evidence == ()


def test_unnamed_column_is_repeatable() -> None:
    run = request(facts(unnamed=(1, 2)))
    assert UnnamedColumnDetector().run(run) == UnnamedColumnDetector().run(run)


def test_unnamed_column_end_to_end_csv_and_xlsx() -> None:
    store = AnalysisStore()
    csv_analysis = create_analysis_from_upload(
        store, content=b"a,,c\n1,2,3\n4,5,6\n", original_filename="x.csv"
    )
    xlsx_analysis = create_analysis_from_upload(
        store,
        content=build_xlsx({"Sheet1": [["a", None, "c"], ["1", "2", "3"]]}),
        original_filename="x.xlsx",
        dataset_format=DatasetFormat.XLSX,
        selected_worksheet="Sheet1",
    )
    for created in (csv_analysis, xlsx_analysis):
        completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)
        assert completed.state is AnalysisState.COMPLETED
        (finding,) = [f for f in completed.findings if f.detector_id == UNNAMED_ID]
        assert [c.original_name for c in finding.affected_columns] == ["column_1"]


def test_a_whitespace_only_header_is_a_name_and_is_not_flagged() -> None:
    """Documented limitation: the parser treats `' '` as a name."""
    projected = project_ingest_facts(parse_csv(b"a, ,c\n1,2,3\n").parsed_dataset)
    assert projected.unnamed_column_count == 0
    assert UnnamedColumnDetector().run(request(projected)).findings == ()


# ---------------------------------------------------------------------------
# structural.excessive_parse_failures
# ---------------------------------------------------------------------------


def test_excessive_parse_failures_metadata_and_config() -> None:
    detector = ExcessiveParseFailuresDetector()
    assert detector.metadata.detector_id == EXCESSIVE_ID
    assert detector.metadata.category is DetectorCategory.STRUCTURAL
    assert detector.metadata.requires_ingest_facts is True
    config = detector.config_schema.model_validate(detector.metadata.default_configuration)
    assert config.model_dump() == dict(detector.metadata.default_configuration)


@pytest.mark.parametrize(
    "bad",
    [
        {"row_ratio_threshold": 0.0},
        {"row_ratio_threshold": 1.5},
        {"row_ratio_threshold": float("nan")},
        {"cell_ratio_threshold": -0.1},
        {"cell_ratio_threshold": float("inf")},
        {"minimum_count": 0},
        {"unknown_option": 1},
    ],
)
def test_excessive_parse_failures_rejects_invalid_configuration(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ExcessiveParseFailuresDetector.config_schema.model_validate({**DEFAULT_CONFIG, **bad})


def test_excessive_parse_failures_flags_ragged_rows_at_the_threshold() -> None:
    # 5 of 100 rows is exactly the 5 % threshold and exactly the minimum count of 5.
    result = run_excessive(facts(ragged_rows=(1, 2, 3, 4, 5)))
    (finding,) = result.findings
    assert finding.severity is Severity.MEDIUM
    assert [r.row_number for r in finding.affected_row_references] == [1, 2, 3, 4, 5]
    assert "5 of 100 data row(s)" in finding.calculated_observation
    payload = result.evidence[0].structured_payload
    assert payload["ragged_row_count"] == 5 and payload["ragged_row_ratio"] == 0.05


def test_excessive_parse_failures_boundary_just_below_the_row_threshold_is_silent() -> None:
    assert run_excessive(facts(ragged_rows=(1, 2, 3, 4))).findings == ()  # 4 %, and 4 < 5


def test_excessive_parse_failures_needs_both_the_ratio_and_the_minimum_count() -> None:
    # A short file: 2 of 10 rows is 20 %, but below the count floor of 5.
    assert run_excessive(facts(row_count=10, ragged_rows=(1, 2))).findings == ()
    # With the floor lowered the same facts fire.
    assert (
        len(run_excessive(facts(row_count=10, ragged_rows=(1, 2)), minimum_count=2).findings) == 1
    )
    # A large file: 5 rows of 10,000 is at the floor but far below the ratio.
    assert run_excessive(facts(row_count=10_000, ragged_rows=(1, 2, 3, 4, 5))).findings == ()


def test_excessive_parse_failures_flags_unreadable_xlsx_cells() -> None:
    # 20 of 400 cells (100 rows x 4 columns) is 5 %.
    result = run_excessive(facts(formula_cells=12, error_cells=8))
    (finding,) = result.findings
    assert "20 of 400 cell(s)" in finding.calculated_observation
    assert "12 formula(s) without a stored result" in finding.calculated_observation
    assert "8 spreadsheet error value(s)" in finding.calculated_observation
    assert finding.affected_row_references == ()
    payload = result.evidence[0].structured_payload
    assert payload["unreadable_cell_count"] == 20 and payload["unreadable_cell_ratio"] == 0.05


def test_excessive_parse_failures_boundary_just_below_the_cell_threshold_is_silent() -> None:
    assert run_excessive(facts(formula_cells=10, error_cells=9)).findings == ()  # 19 of 400


def test_excessive_parse_failures_reports_both_measures_in_one_finding() -> None:
    result = run_excessive(facts(ragged_rows=(1, 2, 3, 4, 5, 6), formula_cells=30))
    (finding,) = result.findings
    assert "data row(s)" in finding.calculated_observation
    assert "cell(s)" in finding.calculated_observation


def test_excessive_parse_failures_severity_is_high_at_half() -> None:
    mild = run_excessive(facts(ragged_rows=tuple(range(MAX_REFERENCES)), ragged_count=49))
    severe = run_excessive(facts(ragged_rows=tuple(range(MAX_REFERENCES)), ragged_count=50))
    assert mild.findings[0].severity is Severity.MEDIUM
    assert severe.findings[0].severity is Severity.HIGH


def test_excessive_parse_failures_respects_configured_thresholds() -> None:
    strict = run_excessive(facts(ragged_rows=(1,)), row_ratio_threshold=0.01, minimum_count=1)
    assert len(strict.findings) == 1
    lenient = run_excessive(facts(ragged_rows=tuple(range(10))), row_ratio_threshold=0.5)
    assert lenient.findings == ()


def test_excessive_parse_failures_handles_zero_rows_and_zero_columns() -> None:
    assert run_excessive(facts(row_count=0, column_count=3)).findings == ()
    assert run_excessive(facts(row_count=10, column_count=0, formula_cells=10)).findings != ()


def test_excessive_parse_failures_clamps_a_count_larger_than_the_rows() -> None:
    result = run_excessive(facts(row_count=10, ragged_rows=(1,), ragged_count=40))
    assert result.evidence[0].structured_payload["ragged_row_ratio"] == 1.0


def test_excessive_parse_failures_without_facts_produces_nothing_when_run_directly() -> None:
    result = run_excessive(None)
    assert result.findings == () and result.evidence == ()


def test_excessive_parse_failures_is_repeatable() -> None:
    projected = facts(ragged_rows=(1, 2, 3, 4, 5), formula_cells=50)
    assert run_excessive(projected) == run_excessive(projected)


def test_a_few_trailing_blank_csv_lines_do_not_fire_the_detector() -> None:
    """Known false-positive guard: the parser reads a blank CSV line as a ragged
    row, so the count floor must keep a few trailing blank lines silent."""
    parsed = parse_csv(b"a,b\n" + b"1,2\n" * 200 + b"\n\n")
    projected = project_ingest_facts(parsed.parsed_dataset)
    assert projected.ragged_row_count == 2
    assert run_excessive(projected).findings == ()


def test_excessive_parse_failures_end_to_end_csv() -> None:
    body = b"a,b,c\n" + b"1,2,3\n" * 20 + b"1\n" * 10
    store = AnalysisStore()
    created = create_analysis_from_upload(store, content=body, original_filename="r.csv")

    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert completed.state is AnalysisState.COMPLETED
    (finding,) = [f for f in completed.findings if f.detector_id == EXCESSIVE_ID]
    assert "10 of 30 data row(s)" in finding.calculated_observation
    assert finding.severity is Severity.MEDIUM


def test_excessive_parse_failures_end_to_end_xlsx() -> None:
    rows: list[list[Cell]] = [["a", "b"]]
    rows += [[("formula", "1+1", None), ("error", "#REF!")] for _ in range(10)]
    store = AnalysisStore()
    created = create_analysis_from_upload(
        store,
        content=build_xlsx({"Sheet1": rows}),
        original_filename="r.xlsx",
        dataset_format=DatasetFormat.XLSX,
        selected_worksheet="Sheet1",
    )

    completed = run_analysis(store, created.analysis_id, now=FIXED_NOW)

    assert completed.state is AnalysisState.COMPLETED
    (finding,) = [f for f in completed.findings if f.detector_id == EXCESSIVE_ID]
    assert "20 of 20 cell(s)" in finding.calculated_observation


# ---------------------------------------------------------------------------
# Privacy: no cell value and no parser message in any finding or evidence
# ---------------------------------------------------------------------------

SECRET = "TOPSECRET-VALUE-4711"


def test_no_cell_value_or_parser_message_reaches_a_finding_or_evidence() -> None:
    header = f"a,,{SECRET}\n".encode()
    body = header + f"{SECRET},{SECRET}\n".encode() * 12 + f"{SECRET}\n".encode() * 12
    parsed = parse_csv(body)
    # The parser's own messages name rows and fields; the detectors must not echo them.
    assert any(w.message for w in parsed.parsed_dataset.parsing_warnings)
    projected = project_ingest_facts(parsed.parsed_dataset)

    unnamed = UnnamedColumnDetector().run(request(projected))
    excessive = run_excessive(projected)

    assert unnamed.findings and excessive.findings
    for result in (unnamed, excessive):
        text = evidence_text(result)
        assert SECRET not in text
        assert "fields, expected" not in text  # the parser's ragged-row message
        assert "empty header cell" not in text  # the parser's empty-name message


def test_the_xlsx_error_text_never_reaches_a_finding_or_evidence() -> None:
    rows: list[list[Cell]] = [["a", "b"]]
    rows += [[("error", "#SECRET_ERROR!"), ("error", "#SECRET_ERROR!")] for _ in range(10)]
    parsed = parse_xlsx(build_xlsx({"Sheet1": rows}), worksheet="Sheet1")
    projected = project_ingest_facts(parsed.parsed_dataset)

    result = run_excessive(projected)

    assert result.findings
    assert "SECRET_ERROR" not in evidence_text(result)
    assert "literal text" not in evidence_text(result)


# ---------------------------------------------------------------------------
# Registry interoperation and unchanged behavior
# ---------------------------------------------------------------------------


def test_the_new_detectors_are_registered_with_unique_ids_in_the_structural_category() -> None:
    by_id = {d.metadata.detector_id: d for d in DETECTORS}
    assert len(by_id) == len(DETECTORS)
    for detector_id in (EMPTY_ID, UNNAMED_ID, EXCESSIVE_ID):
        assert by_id[detector_id].metadata.category is DetectorCategory.STRUCTURAL


def test_a_clean_dataset_yields_no_finding_from_any_new_detector() -> None:
    parsed = parse_csv(b"a,b\n1,2\n3,4\n")
    profile = compute_dataset_profile(
        parsed.parsed_dataset.columns,
        parsed.rows,
        parsed.parsed_dataset.sampling,
        as_of=ANALYSIS_TIMESTAMP.date(),
    )
    keyed = tuple(
        {column.internal_key: row[column.ordinal] for column in parsed.parsed_dataset.columns}
        for row in parsed.rows
    )
    results = run_detectors(
        list(DETECTORS),
        dataset_profile=profile,
        rows=keyed,
        row_references=parsed.parsed_dataset.row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        ingest_facts=project_ingest_facts(parsed.parsed_dataset),
    )
    flagged = {r.detector_id for r in results if r.findings}
    assert flagged.isdisjoint({EMPTY_ID, UNNAMED_ID, EXCESSIVE_ID})
    assert all(
        r.status is DetectorRunStatus.SUCCESS
        for r in results
        if r.detector_id in {EMPTY_ID, UNNAMED_ID, EXCESSIVE_ID}
    )
