"""Tests for the inspector reads added by `UX-06` part b (D-074): a window
reached from an observation's example rows, and a window for a column-wide
finding (an existing safe anchor, otherwise the start of the file).

The properties that matter most:

- only rows the server itself offers can be the centre of a window, and every
  other row is refused;
- a start-of-file window is never marked as if the finding pointed at it;
- reading any of these windows changes no state, AI payload, evidence, finding
  or report, and the visible row text reaches none of them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from tests.analysis.test_service import (
    _ROW_CONTEXT_CSV,
    FIXED_NOW,
    _make_completed_analysis,
    _make_evidence,
    _make_finding,
)
from trusttable_backend.ai_boundary.prompt import build_safe_prompt
from trusttable_backend.analysis.service import (
    Analysis,
    AnalysisNotFoundError,
    AnalysisStore,
    FindingHasAffectedRowsError,
    FindingNotFoundError,
    NoRowsToShowError,
    ObservationNotFoundError,
    RowNotInObservationError,
    RowNotInScopeError,
    get_column_wide_finding_window,
    get_finding,
    get_finding_evidence,
    get_observation_row_context,
)
from trusttable_backend.detectors.contract import FindingCandidate
from trusttable_backend.domain.observation import Observation, ObservationKind
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.row_context import (
    ANCHOR_OBSERVATION_EXAMPLE,
    ANCHOR_START_OF_FILE,
    SCOPE_COLUMN_WIDE_FINDING,
    SCOPE_OBSERVATION,
)
from trusttable_backend.domain.value_objects import ColumnReference, RowReference
from trusttable_backend.explanation.ai_explanation import build_finding_explanation_envelope
from trusttable_backend.exports.report_build import build_report_snapshot
from trusttable_backend.exports.report_snapshot import ReportVersions

COL_A = ColumnReference(original_name="col_a", internal_key="col_a", ordinal=0)
COL_B = ColumnReference(original_name="col_b", internal_key="col_b", ordinal=1)


def _observation(
    observation_id: str = "structural.mixed_types.observation.col_a",
    *,
    columns: tuple[ColumnReference, ...] = (COL_A,),
    rows: tuple[int, ...] = (1, 3),
) -> Observation:
    return Observation(
        observation_id=observation_id,
        kind=ObservationKind.VALUE_EVIDENCE,
        producer_detector_id="structural.mixed_types",
        producer_version="1",
        summary="A neutral statement of what was counted.",
        affected_columns=columns,
        affected_row_references=tuple(RowReference(row_number=row) for row in rows),
        scope=SamplingScope.FULL,
    )


def _column_wide_finding(columns: tuple[ColumnReference, ...] = (COL_A,)) -> FindingCandidate:
    return replace(_make_finding(), affected_columns=columns)


def _store_with(
    *,
    findings: Sequence[FindingCandidate] = (),
    observations: Sequence[Observation] = (),
    content: bytes = _ROW_CONTEXT_CSV,
) -> tuple[AnalysisStore, Analysis]:
    analysis = _make_completed_analysis(
        content=content,
        findings=tuple(findings),
        priority_scores=tuple(50.0 for _ in findings),
        observations=tuple(observations),
    )
    store = AnalysisStore()
    store.add(analysis)
    return store, analysis


# --- observation windows ---------------------------------------------------------


def test_observation_window_is_centred_on_one_of_its_own_example_rows() -> None:
    store, analysis = _store_with(observations=(_observation(),))

    scoped = get_observation_row_context(
        store, analysis.analysis_id, "structural.mixed_types.observation.col_a", anchor_row=3
    )

    assert scoped.scope_kind == SCOPE_OBSERVATION
    assert scoped.anchor_source == ANCHOR_OBSERVATION_EXAMPLE
    assert scoped.anchor_rows == (1, 3)
    marked = {
        entry.row_reference.row_number: entry.is_affected_by_finding for entry in scoped.window.rows
    }
    assert marked == {0: False, 1: True, 2: False, 3: True, 4: False}
    assert [e.row_reference.row_number for e in scoped.window.rows if e.is_anchor] == [3]


def test_observation_window_refuses_any_row_that_is_not_an_example_row() -> None:
    store, analysis = _store_with(observations=(_observation(),))

    for row in (0, 2, 4, 99, -1):
        with pytest.raises(RowNotInObservationError) as excinfo:
            get_observation_row_context(
                store,
                analysis.analysis_id,
                "structural.mixed_types.observation.col_a",
                anchor_row=row,
            )
        assert excinfo.value.anchor_row == row


def test_an_observation_with_no_example_rows_has_no_window() -> None:
    store, analysis = _store_with(observations=(_observation(rows=()),))

    with pytest.raises(RowNotInObservationError):
        get_observation_row_context(
            store, analysis.analysis_id, "structural.mixed_types.observation.col_a", anchor_row=0
        )


def test_observation_window_refuses_an_unknown_observation_and_an_unknown_analysis() -> None:
    store, analysis = _store_with(observations=(_observation(),))

    with pytest.raises(ObservationNotFoundError):
        get_observation_row_context(store, analysis.analysis_id, "nope", anchor_row=1)
    with pytest.raises(AnalysisNotFoundError):
        get_observation_row_context(store, "unknown-id", "x", anchor_row=1)


def test_observation_window_does_not_read_another_observations_rows() -> None:
    store, analysis = _store_with(
        observations=(
            _observation("a.observation.one", rows=(1,)),
            _observation("a.observation.two", rows=(3,)),
        )
    )

    with pytest.raises(RowNotInObservationError):
        get_observation_row_context(store, analysis.analysis_id, "a.observation.one", anchor_row=3)
    scoped = get_observation_row_context(
        store, analysis.analysis_id, "a.observation.one", anchor_row=1
    )
    assert scoped.anchor_rows == (1,)


# --- column-wide finding windows -----------------------------------------------


def test_a_column_wide_finding_uses_the_example_rows_of_observations_about_its_columns() -> None:
    store, analysis = _store_with(
        findings=(_column_wide_finding((COL_A,)),),
        observations=(
            _observation("o.about.col_a", columns=(COL_A,), rows=(3, 1)),
            _observation("o.about.col_b", columns=(COL_B,), rows=(4,)),
        ),
    )

    scoped = get_column_wide_finding_window(store, analysis.analysis_id, "0")

    assert scoped.scope_kind == SCOPE_COLUMN_WIDE_FINDING
    assert scoped.anchor_source == ANCHOR_OBSERVATION_EXAMPLE
    # Only the observation about the finding's own column, ascending and unique.
    assert scoped.anchor_rows == (1, 3)
    assert [e.row_reference.row_number for e in scoped.window.rows if e.is_anchor] == [1]
    assert {e.row_reference.row_number for e in scoped.window.rows if e.is_affected_by_finding} == {
        1,
        3,
    }


def test_a_finding_about_several_columns_is_offered_the_rows_of_an_observation_about_any_one() -> (
    None
):
    store, analysis = _store_with(
        findings=(_column_wide_finding((COL_A, COL_B)),),
        observations=(_observation("o.about.col_b", columns=(COL_B,), rows=(2, 4)),),
    )

    scoped = get_column_wide_finding_window(store, analysis.analysis_id, "0")

    assert scoped.anchor_source == ANCHOR_OBSERVATION_EXAMPLE
    assert scoped.anchor_rows == (2, 4)


def test_the_offered_example_rows_are_capped_and_ascending_so_the_list_stays_meaningful() -> None:
    content = ("col_a,col_b\n" + "".join(f"a{i},b{i}\n" for i in range(70))).encode()
    store, analysis = _store_with(
        findings=(_column_wide_finding((COL_A,)),),
        observations=(
            _observation("o.third", rows=tuple(range(40, 60))),
            _observation("o.second", rows=tuple(range(20, 40))),
            _observation("o.first", rows=tuple(range(0, 20))),
        ),
        content=content,
    )

    scoped = get_column_wide_finding_window(store, analysis.analysis_id, "0")

    assert scoped.anchor_rows == tuple(range(20))
    assert {
        e.row_reference.row_number for e in scoped.window.rows if e.is_affected_by_finding
    } <= set(range(20))
    # A row beyond the cap is not offered, even though an observation lists it.
    with pytest.raises(RowNotInScopeError):
        get_column_wide_finding_window(store, analysis.analysis_id, "0", anchor_row=20)


def test_a_column_wide_finding_may_choose_only_among_the_rows_the_server_offers() -> None:
    store, analysis = _store_with(
        findings=(_column_wide_finding(),), observations=(_observation(rows=(1, 3)),)
    )

    scoped = get_column_wide_finding_window(store, analysis.analysis_id, "0", anchor_row=3)
    assert [e.row_reference.row_number for e in scoped.window.rows if e.is_anchor] == [3]
    for row in (0, 2, 4, 99):
        with pytest.raises(RowNotInScopeError) as excinfo:
            get_column_wide_finding_window(store, analysis.analysis_id, "0", anchor_row=row)
        assert excinfo.value.anchor_row == row


def test_without_an_existing_anchor_a_column_wide_finding_gets_only_the_start_of_the_file() -> None:
    store, analysis = _store_with(
        findings=(_column_wide_finding((COL_A,)),),
        # An observation about a different column offers nothing for this finding.
        observations=(_observation(columns=(COL_B,), rows=(2,)),),
    )

    scoped = get_column_wide_finding_window(store, analysis.analysis_id, "0")

    assert scoped.anchor_source == ANCHOR_START_OF_FILE
    assert scoped.anchor_rows == (0,)
    assert [e.row_reference.row_number for e in scoped.window.rows if e.is_anchor] == [0]
    # The start of a file is not evidence of the finding: nothing is marked.
    assert not any(e.is_affected_by_finding for e in scoped.window.rows)
    # And no other row can be asked for, not even one of the other observation's.
    for row in (1, 2, 4):
        with pytest.raises(RowNotInScopeError):
            get_column_wide_finding_window(store, analysis.analysis_id, "0", anchor_row=row)


def test_a_finding_that_names_no_column_gets_the_start_of_the_file_not_every_observation() -> None:
    store, analysis = _store_with(
        findings=(_column_wide_finding(()),), observations=(_observation(rows=(1, 3)),)
    )

    scoped = get_column_wide_finding_window(store, analysis.analysis_id, "0")

    assert scoped.anchor_source == ANCHOR_START_OF_FILE
    assert scoped.anchor_rows == (0,)


def test_a_finding_that_names_rows_is_not_read_through_the_column_wide_window() -> None:
    finding = _make_finding(affected_row_references=(RowReference(row_number=2),))
    store, analysis = _store_with(findings=(finding,), observations=(_observation(),))

    with pytest.raises(FindingHasAffectedRowsError):
        get_column_wide_finding_window(store, analysis.analysis_id, "0")


def test_column_wide_window_refuses_an_unknown_finding_and_an_unknown_analysis() -> None:
    store, analysis = _store_with(findings=(_column_wide_finding(),))

    with pytest.raises(FindingNotFoundError):
        get_column_wide_finding_window(store, analysis.analysis_id, "7")
    with pytest.raises(AnalysisNotFoundError):
        get_column_wide_finding_window(store, "unknown-id", "0")


def test_a_file_without_a_data_row_has_no_window() -> None:
    store, analysis = _store_with(findings=(_column_wide_finding(),), content=b"col_a,col_b\n")

    with pytest.raises(NoRowsToShowError):
        get_column_wide_finding_window(store, analysis.analysis_id, "0")


def test_a_stale_example_row_beyond_the_file_is_refused_not_indexed() -> None:
    store, analysis = _store_with(observations=(_observation(rows=(99,)),))

    with pytest.raises(NoRowsToShowError):
        get_observation_row_context(
            store, analysis.analysis_id, "structural.mixed_types.observation.col_a", anchor_row=99
        )


def test_the_new_windows_keep_the_same_bounds_as_a_finding_window() -> None:
    store, analysis = _store_with(
        findings=(_column_wide_finding(),), observations=(_observation(rows=(2,)),)
    )

    scoped = get_observation_row_context(
        store,
        analysis.analysis_id,
        "structural.mixed_types.observation.col_a",
        anchor_row=2,
        before=1000,
        after=1000,
    )

    assert scoped.window.max_window == 25
    assert scoped.window.requested_before == 1000
    assert scoped.window.actual_before == 2
    assert scoped.window.truncated_at_start is True


# --- the windows change nothing else ---------------------------------------------


def test_reading_any_scoped_window_changes_no_state_ai_payload_evidence_or_report() -> None:
    """Invariant 15 (`docs/domain-model.md`) for the new entry points: the row
    text a window shows reaches no AI payload, evidence, finding, report or
    stored state, and reading it changes none of them."""
    evidence = (_make_evidence(),)
    finding = replace(_column_wide_finding(), evidence_ids=("evidence-1",))
    observation = _observation(rows=(1, 3))
    analysis = _make_completed_analysis(
        content=_ROW_CONTEXT_CSV,
        findings=(finding,),
        priority_scores=(50.0,),
        evidence=evidence,
        observations=(observation,),
    )
    store = AnalysisStore()
    store.add(analysis)
    versions = ReportVersions(application_version="0")

    def snapshot() -> tuple[object, ...]:
        prompt = build_safe_prompt(build_finding_explanation_envelope(finding, evidence))
        report = build_report_snapshot(
            analysis, report_id="r1", generated_at=FIXED_NOW, versions=versions
        )
        return (
            prompt,
            report.markdown,
            report.content_sha256,
            get_finding_evidence(store, analysis.analysis_id, "0"),
            get_finding(store, analysis.analysis_id, "0"),
            store.get(analysis.analysis_id),
        )

    before = snapshot()
    for row in (1, 3):
        get_observation_row_context(
            store, analysis.analysis_id, observation.observation_id, anchor_row=row
        )
        get_column_wide_finding_window(store, analysis.analysis_id, "0", anchor_row=row)
    after = snapshot()

    assert after == before
    for text in ("r1a", "r3b", "r0a"):
        assert text not in str(after[0])
        assert text not in str(after[1])
