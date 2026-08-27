"""Tests for the typed parsing contracts (ING-01).

Covers this package's acceptance criteria AC-03..AC-08 (`Dataset`,
`DatasetFormat`/`DatasetSourceType`, `WorksheetMetadata`, `ParsingWarning`,
`SampleMetadata`, `ParsedDataset`): positive, negative
(invariant-violation), and boundary cases, including `ParsedDataset`'s
cross-field aggregate invariants.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.domain.parsing import (
    Dataset,
    DatasetFormat,
    DatasetSourceType,
    ParsedDataset,
    ParsingWarning,
    SampleMetadata,
    SamplingScope,
    WorksheetMetadata,
)
from trusttable_backend.domain.value_objects import ColumnReference, RowReference

CREATED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def make_dataset(**overrides: object) -> Dataset:
    fields: dict[str, object] = {
        "dataset_id": "ds-1",
        "original_filename": "sales.csv",
        "stored_filename": "ds-1.csv",
        "format": DatasetFormat.CSV,
        "byte_size": 1024,
        "content_hash": "sha256:abc123",
        "selected_worksheet": None,
        "created_at": CREATED_AT,
        "deleted_at": None,
        "storage_location": "/data/ds-1.csv",
        "source_type": DatasetSourceType.UPLOAD,
    }
    fields.update(overrides)
    return Dataset(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-03/AC-04: Dataset, DatasetFormat, DatasetSourceType
# ---------------------------------------------------------------------------


def test_dataset_constructs_with_valid_fields() -> None:
    dataset = make_dataset()

    assert dataset.dataset_id == "ds-1"
    assert dataset.format is DatasetFormat.CSV
    assert dataset.source_type is DatasetSourceType.UPLOAD
    assert dataset.deleted_at is None


def test_dataset_is_immutable() -> None:
    dataset = make_dataset()

    with pytest.raises(AttributeError):
        dataset.dataset_id = "ds-2"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name",
    ["dataset_id", "original_filename", "stored_filename", "content_hash", "storage_location"],
)
def test_dataset_rejects_empty_required_strings(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_dataset(**{field_name: ""})


def test_dataset_rejects_negative_byte_size() -> None:
    with pytest.raises(ValueError, match="byte_size"):
        make_dataset(byte_size=-1)


def test_dataset_accepts_zero_byte_size_boundary() -> None:
    dataset = make_dataset(byte_size=0)
    assert dataset.byte_size == 0


def test_dataset_rejects_deleted_at_before_created_at() -> None:
    with pytest.raises(ValueError, match="deleted_at"):
        make_dataset(deleted_at=datetime(2026, 8, 25, tzinfo=UTC))


def test_dataset_accepts_deleted_at_equal_to_created_at_boundary() -> None:
    dataset = make_dataset(deleted_at=CREATED_AT)
    assert dataset.deleted_at == CREATED_AT


def test_dataset_format_is_a_closed_enumeration() -> None:
    assert {member.value for member in DatasetFormat} == {"csv", "xlsx"}


def test_dataset_source_type_is_a_closed_enumeration() -> None:
    assert {member.value for member in DatasetSourceType} == {"upload", "bundled_demo"}


# ---------------------------------------------------------------------------
# AC-05: WorksheetMetadata
# ---------------------------------------------------------------------------


def test_worksheet_metadata_constructs_with_valid_fields() -> None:
    sheet = WorksheetMetadata(
        name="Sheet1", index=0, row_count=10, column_count=5, is_selected=True
    )

    assert sheet.name == "Sheet1"
    assert sheet.is_selected is True


def test_worksheet_metadata_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        WorksheetMetadata(name="", index=0, row_count=10, column_count=5, is_selected=True)


def test_worksheet_metadata_rejects_negative_index() -> None:
    with pytest.raises(ValueError, match="index"):
        WorksheetMetadata(name="Sheet1", index=-1, row_count=10, column_count=5, is_selected=True)


def test_worksheet_metadata_rejects_negative_row_count() -> None:
    with pytest.raises(ValueError, match="row_count"):
        WorksheetMetadata(name="Sheet1", index=0, row_count=-1, column_count=5, is_selected=True)


def test_worksheet_metadata_rejects_negative_column_count() -> None:
    with pytest.raises(ValueError, match="column_count"):
        WorksheetMetadata(name="Sheet1", index=0, row_count=10, column_count=-1, is_selected=True)


def test_worksheet_metadata_accepts_zero_counts_boundary() -> None:
    sheet = WorksheetMetadata(
        name="Sheet1", index=0, row_count=0, column_count=0, is_selected=False
    )
    assert sheet.row_count == 0
    assert sheet.column_count == 0


# ---------------------------------------------------------------------------
# AC-06: ParsingWarning
# ---------------------------------------------------------------------------


def test_parsing_warning_constructs_with_required_fields_only() -> None:
    warning = ParsingWarning(code="parsing.truncated_row", message="Row truncated")

    assert warning.code == "parsing.truncated_row"
    assert warning.column is None
    assert warning.row is None


def test_parsing_warning_constructs_with_optional_references() -> None:
    column = ColumnReference(original_name="Qty", internal_key="qty", ordinal=0)
    row = RowReference(row_number=3)
    warning = ParsingWarning(
        code="parsing.truncated_row", message="Row truncated", column=column, row=row
    )

    assert warning.column == column
    assert warning.row == row


def test_parsing_warning_rejects_empty_message() -> None:
    with pytest.raises(ValueError, match="message"):
        ParsingWarning(code="parsing.truncated_row", message="")


def test_parsing_warning_rejects_non_namespaced_code() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        ParsingWarning(code="truncated_row", message="Row truncated")


# ---------------------------------------------------------------------------
# AC-07: SampleMetadata
# ---------------------------------------------------------------------------


def test_sample_metadata_full_scope_valid() -> None:
    sample = SampleMetadata(scope=SamplingScope.FULL, population_size=100, sample_size=100)
    assert sample.method is None


def test_sample_metadata_full_scope_rejects_mismatched_sample_size() -> None:
    with pytest.raises(ValueError, match="full scope"):
        SampleMetadata(scope=SamplingScope.FULL, population_size=100, sample_size=99)


def test_sample_metadata_full_scope_rejects_declared_method() -> None:
    with pytest.raises(ValueError, match="full scope"):
        SampleMetadata(
            scope=SamplingScope.FULL, population_size=100, sample_size=100, method="random"
        )


def test_sample_metadata_sampled_scope_valid() -> None:
    sample = SampleMetadata(
        scope=SamplingScope.SAMPLED, population_size=100, sample_size=10, method="random"
    )
    assert sample.method == "random"


def test_sample_metadata_sampled_scope_requires_method() -> None:
    with pytest.raises(ValueError, match="sampled scope"):
        SampleMetadata(scope=SamplingScope.SAMPLED, population_size=100, sample_size=10)


def test_sample_metadata_sampled_scope_accepts_full_size_boundary() -> None:
    sample = SampleMetadata(
        scope=SamplingScope.SAMPLED, population_size=100, sample_size=100, method="random"
    )
    assert sample.sample_size == sample.population_size


@pytest.mark.parametrize("scope", [SamplingScope.FULL, SamplingScope.SAMPLED])
def test_sample_metadata_rejects_sample_size_exceeding_population(
    scope: SamplingScope,
) -> None:
    kwargs: dict[str, object] = {"scope": scope, "population_size": 10, "sample_size": 11}
    if scope is SamplingScope.SAMPLED:
        kwargs["method"] = "random"

    with pytest.raises(ValueError, match="sample_size"):
        SampleMetadata(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-08: ParsedDataset
# ---------------------------------------------------------------------------


def make_columns() -> tuple[ColumnReference, ...]:
    return (
        ColumnReference(original_name="Order ID", internal_key="order_id", ordinal=0),
        ColumnReference(original_name="Qty", internal_key="qty", ordinal=1),
    )


def make_full_sampling(population_size: int) -> SampleMetadata:
    return SampleMetadata(
        scope=SamplingScope.FULL, population_size=population_size, sample_size=population_size
    )


def test_parsed_dataset_constructs_for_csv_with_no_worksheets() -> None:
    columns = make_columns()
    dataset = ParsedDataset(
        columns=columns,
        row_count=2,
        format=DatasetFormat.CSV,
        worksheets=(),
        parsing_warnings=(),
        sampling=make_full_sampling(2),
        row_references=(RowReference(row_number=0), RowReference(row_number=1)),
    )

    assert dataset.row_count == 2
    assert dataset.worksheets == ()


def test_parsed_dataset_is_immutable() -> None:
    dataset = ParsedDataset(
        columns=make_columns(),
        row_count=2,
        format=DatasetFormat.CSV,
        worksheets=(),
        parsing_warnings=(),
        sampling=make_full_sampling(2),
        row_references=(RowReference(row_number=0), RowReference(row_number=1)),
    )

    with pytest.raises(AttributeError):
        dataset.row_count = 3  # type: ignore[misc]


def test_parsed_dataset_rejects_duplicate_internal_key() -> None:
    columns = (
        ColumnReference(original_name="Order ID", internal_key="order_id", ordinal=0),
        ColumnReference(original_name="Order Id 2", internal_key="order_id", ordinal=1),
    )
    with pytest.raises(ValueError, match="internal_key"):
        ParsedDataset(
            columns=columns,
            row_count=1,
            format=DatasetFormat.CSV,
            worksheets=(),
            parsing_warnings=(),
            sampling=make_full_sampling(1),
            row_references=(RowReference(row_number=0),),
        )


def test_parsed_dataset_rejects_duplicate_ordinal() -> None:
    columns = (
        ColumnReference(original_name="Order ID", internal_key="order_id", ordinal=0),
        ColumnReference(original_name="Qty", internal_key="qty", ordinal=0),
    )
    with pytest.raises(ValueError, match="ordinal"):
        ParsedDataset(
            columns=columns,
            row_count=1,
            format=DatasetFormat.CSV,
            worksheets=(),
            parsing_warnings=(),
            sampling=make_full_sampling(1),
            row_references=(RowReference(row_number=0),),
        )


def test_parsed_dataset_rejects_worksheets_for_csv_format() -> None:
    sheet = WorksheetMetadata(name="Sheet1", index=0, row_count=1, column_count=2, is_selected=True)
    with pytest.raises(ValueError, match="csv format"):
        ParsedDataset(
            columns=make_columns(),
            row_count=1,
            format=DatasetFormat.CSV,
            worksheets=(sheet,),
            parsing_warnings=(),
            sampling=make_full_sampling(1),
            row_references=(RowReference(row_number=0),),
        )


def test_parsed_dataset_requires_worksheets_for_xlsx_format() -> None:
    with pytest.raises(ValueError, match="xlsx format"):
        ParsedDataset(
            columns=make_columns(),
            row_count=1,
            format=DatasetFormat.XLSX,
            worksheets=(),
            parsing_warnings=(),
            sampling=make_full_sampling(1),
            row_references=(RowReference(row_number=0),),
        )


def test_parsed_dataset_xlsx_requires_exactly_one_selected_worksheet() -> None:
    sheets = (
        WorksheetMetadata(name="Sheet1", index=0, row_count=1, column_count=2, is_selected=False),
        WorksheetMetadata(name="Sheet2", index=1, row_count=1, column_count=2, is_selected=False),
    )
    with pytest.raises(ValueError, match="is_selected"):
        ParsedDataset(
            columns=make_columns(),
            row_count=1,
            format=DatasetFormat.XLSX,
            worksheets=sheets,
            parsing_warnings=(),
            sampling=make_full_sampling(1),
            row_references=(RowReference(row_number=0),),
        )


def test_parsed_dataset_xlsx_rejects_multiple_selected_worksheets() -> None:
    sheets = (
        WorksheetMetadata(name="Sheet1", index=0, row_count=1, column_count=2, is_selected=True),
        WorksheetMetadata(name="Sheet2", index=1, row_count=1, column_count=2, is_selected=True),
    )
    with pytest.raises(ValueError, match="is_selected"):
        ParsedDataset(
            columns=make_columns(),
            row_count=1,
            format=DatasetFormat.XLSX,
            worksheets=sheets,
            parsing_warnings=(),
            sampling=make_full_sampling(1),
            row_references=(RowReference(row_number=0),),
        )


def test_parsed_dataset_xlsx_constructs_with_exactly_one_selected_worksheet() -> None:
    sheets = (
        WorksheetMetadata(name="Sheet1", index=0, row_count=1, column_count=2, is_selected=True),
    )
    dataset = ParsedDataset(
        columns=make_columns(),
        row_count=1,
        format=DatasetFormat.XLSX,
        worksheets=sheets,
        parsing_warnings=(),
        sampling=make_full_sampling(1),
        row_references=(RowReference(row_number=0),),
    )
    assert dataset.worksheets == sheets


def test_parsed_dataset_rejects_row_references_length_mismatch() -> None:
    with pytest.raises(ValueError, match="row_references"):
        ParsedDataset(
            columns=make_columns(),
            row_count=2,
            format=DatasetFormat.CSV,
            worksheets=(),
            parsing_warnings=(),
            sampling=make_full_sampling(2),
            row_references=(RowReference(row_number=0),),
        )


def test_parsed_dataset_row_references_match_sampled_scope_size() -> None:
    sampling = SampleMetadata(
        scope=SamplingScope.SAMPLED, population_size=10, sample_size=3, method="random"
    )
    dataset = ParsedDataset(
        columns=make_columns(),
        row_count=10,
        format=DatasetFormat.CSV,
        worksheets=(),
        parsing_warnings=(),
        sampling=sampling,
        row_references=(
            RowReference(row_number=0),
            RowReference(row_number=4),
            RowReference(row_number=9),
        ),
    )
    assert len(dataset.row_references) == 3
