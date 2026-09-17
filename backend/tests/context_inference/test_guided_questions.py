"""Tests for deterministic guided-question generation (CTX-03, WP-058).

Covers this package's acceptance criteria AC-02..AC-06: per-field
generation/skip behavior, the four role fields' immunity, the maximal
and zero cases, fixed order, determinism, and a real end-to-end check
against the committed `demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from trusttable_backend.context_inference.guided_questions import (
    MAX_GUIDED_QUESTIONS,
    generate_guided_questions,
)
from trusttable_backend.context_inference.heuristics import (
    consolidate_dataset_context,
    infer_dataset_context,
)
from trusttable_backend.domain.context import (
    ConfirmationState,
    ContextField,
    ContextFieldValue,
    DatasetContext,
)
from trusttable_backend.domain.value_objects import Provenance
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"

_ELIGIBLE_FIELDS = (
    ContextField.PROBABLE_DOMAIN,
    ContextField.ROW_GRAIN,
    ContextField.PRIMARY_ENTITY,
    ContextField.CURRENCY_BEHAVIOR,
    ContextField.EXPECTED_BUSINESS_RULES,
)
_ROLE_FIELDS = (
    ContextField.CANDIDATE_KEYS,
    ContextField.BUSINESS_DATES,
    ContextField.MEASURE_ROLES,
    ContextField.DIMENSIONS,
)


def _unknown_value() -> ContextFieldValue:
    return ContextFieldValue(
        value="unknown",
        confidence=0.0,
        inference_source=Provenance.DETERMINISTIC_FALLBACK,
        confirmation_state=ConfirmationState.UNKNOWN,
        evidence_ids=(),
    )


def _unknown_role_value() -> ContextFieldValue:
    return ContextFieldValue(
        value=(),
        confidence=0.0,
        inference_source=Provenance.DETERMINISTIC_FALLBACK,
        confirmation_state=ConfirmationState.UNKNOWN,
        evidence_ids=(),
    )


def _resolved_value(state: ConfirmationState = ConfirmationState.INFERRED) -> ContextFieldValue:
    return ContextFieldValue(
        value="some resolved value",
        confidence=0.8,
        inference_source=Provenance.CALCULATED,
        confirmation_state=state,
        evidence_ids=(),
    )


def make_dataset_context(
    overrides: dict[ContextField, ContextFieldValue] | None = None,
) -> DatasetContext:
    overrides = overrides or {}
    fields: dict[str, ContextFieldValue] = {}
    for field in ContextField:
        if field in overrides:
            fields[field.value] = overrides[field]
        elif field in _ROLE_FIELDS:
            fields[field.value] = _unknown_role_value()
        else:
            fields[field.value] = _unknown_value()
    return DatasetContext(schema_version="1", **fields)


# ---------------------------------------------------------------------------
# AC-02: per-field generation/skip behavior
# ---------------------------------------------------------------------------


def test_generates_question_for_each_eligible_field_when_unknown() -> None:
    context = make_dataset_context()

    questions = generate_guided_questions(context)

    assert len(questions) == len(_ELIGIBLE_FIELDS)
    assert {q.context_field for q in questions} == set(_ELIGIBLE_FIELDS)


def test_generates_no_question_for_inferred_field() -> None:
    context = make_dataset_context({ContextField.PROBABLE_DOMAIN: _resolved_value()})

    questions = generate_guided_questions(context)

    assert ContextField.PROBABLE_DOMAIN not in {q.context_field for q in questions}
    assert len(questions) == len(_ELIGIBLE_FIELDS) - 1


def test_generates_no_question_for_confirmed_field() -> None:
    context = make_dataset_context(
        {ContextField.ROW_GRAIN: _resolved_value(ConfirmationState.CONFIRMED)}
    )

    questions = generate_guided_questions(context)

    assert ContextField.ROW_GRAIN not in {q.context_field for q in questions}


def test_generates_no_question_for_corrected_field() -> None:
    context = make_dataset_context(
        {ContextField.PRIMARY_ENTITY: _resolved_value(ConfirmationState.CORRECTED)}
    )

    questions = generate_guided_questions(context)

    assert ContextField.PRIMARY_ENTITY not in {q.context_field for q in questions}


# ---------------------------------------------------------------------------
# Role fields are never eligible, regardless of confirmation state
# ---------------------------------------------------------------------------


def test_role_fields_never_produce_a_question_even_when_unknown() -> None:
    context = make_dataset_context()  # role fields default to UNKNOWN here too

    questions = generate_guided_questions(context)

    assert not any(q.context_field in _ROLE_FIELDS for q in questions)


# ---------------------------------------------------------------------------
# AC-02: maximal and zero cases
# ---------------------------------------------------------------------------


def test_maximal_case_yields_exactly_max_guided_questions() -> None:
    context = consolidate_dataset_context(())  # every field UNKNOWN

    questions = generate_guided_questions(context)

    assert len(questions) == MAX_GUIDED_QUESTIONS == 5


def test_zero_case_yields_no_questions() -> None:
    overrides = {field: _resolved_value() for field in _ELIGIBLE_FIELDS}
    context = make_dataset_context(overrides)

    questions = generate_guided_questions(context)

    assert questions == ()


# ---------------------------------------------------------------------------
# Fixed order and determinism
# ---------------------------------------------------------------------------


def test_questions_are_generated_in_fixed_order() -> None:
    context = consolidate_dataset_context(())

    questions = generate_guided_questions(context)

    assert [q.context_field for q in questions] == list(_ELIGIBLE_FIELDS)


def test_generation_is_deterministic() -> None:
    context = consolidate_dataset_context(())

    first = generate_guided_questions(context)
    second = generate_guided_questions(context)

    assert first == second


# ---------------------------------------------------------------------------
# AC-03: no ai_boundary/ai_provider import
# ---------------------------------------------------------------------------


def test_no_ai_boundary_or_ai_provider_import_in_guided_questions_module() -> None:
    module_path = (
        REPO_ROOT
        / "backend"
        / "src"
        / "trusttable_backend"
        / "context_inference"
        / "guided_questions.py"
    )
    source = module_path.read_text(encoding="utf-8")
    import_lines = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert not any("ai_boundary" in line or "ai_provider" in line for line in import_lines)


# ---------------------------------------------------------------------------
# AC-04: no eval/exec
# ---------------------------------------------------------------------------


def test_no_eval_or_exec_in_guided_questions_module() -> None:
    module_path = (
        REPO_ROOT
        / "backend"
        / "src"
        / "trusttable_backend"
        / "context_inference"
        / "guided_questions.py"
    )
    source = module_path.read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


# ---------------------------------------------------------------------------
# AC-06: real end-to-end check against the committed demo dataset
# ---------------------------------------------------------------------------


def test_real_demo_csv_yields_exactly_two_questions() -> None:
    content = DEMO_CSV_PATH.read_bytes()
    parsed = parse_csv(content)
    profile = compute_dataset_profile(
        parsed.parsed_dataset.columns,
        parsed.rows,
        parsed.parsed_dataset.sampling,
        as_of=date(2026, 8, 24),
    )
    context = infer_dataset_context(profile)

    questions = generate_guided_questions(context)

    assert {q.context_field for q in questions} == {
        ContextField.CURRENCY_BEHAVIOR,
        ContextField.EXPECTED_BUSINESS_RULES,
    }
    assert len(questions) == 2
