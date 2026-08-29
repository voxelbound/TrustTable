"""Cross-field detectors (`DET-02` partial), matching
`docs/detector-framework.md` §16's "Cross-field" category: line-total
mismatch. The first detector in the `CROSS_FIELD` category
(`docs/detector-framework.md` §4).

`LineTotalMismatchDetector` recomputes `quantity × unit_price × (1 −
discount_pct/100) × (1 + tax_pct/100)` per row from five configurable,
defaulted column names and flags rows where the dataset's own
`line_total` differs from the recomputed value by more than a one-cent
tolerance. It is the first detector in this catalogue to use a
non-empty `config_schema` — `docs/detector-framework.md` §8's already-
built, previously-unexercised configuration mechanism — since no
confirmed column-role context (`CTX-01`) exists yet to resolve which
columns play which role.

Framework-independent per `docs/architecture.md` §3's "Detectors" layer
rule ("detector modules do not import FastAPI"); `pydantic.BaseModel` is
used for `config_schema`, matching every other detector module.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.evidence import Evidence, EvidenceType
from ..domain.parsing import SamplingScope
from ..domain.value_objects import ColumnReference, Severity
from ..profiling.schemas import InferredColumnType
from .contract import (
    DetectorCategory,
    DetectorMetadata,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    DetectorSupportRequest,
    DetectorWarning,
    ExecutionMetrics,
    FindingCandidate,
    PerformanceClass,
)

_LINE_TOTAL_TOLERANCE = 0.01
"""A `line_total` value is treated as matching the recomputed formula
when the absolute difference is at most one cent. Tied directly to the
2-decimal currency-rounding convention used throughout the demo dataset
and generator (`_format_amount`) — a disclosed, reversible design
choice."""


class _LineTotalMismatchConfig(BaseModel):
    """Configurable, defaulted column-name roles
    (`docs/detector-framework.md` §8) — the standard sales-order naming
    convention by default, independently overridable per role. No
    confirmed column-role context (`CTX-01`) exists yet to resolve these
    automatically."""

    quantity_column: str = Field(default="quantity")
    unit_price_column: str = Field(default="unit_price")
    discount_pct_column: str = Field(default="discount_pct")
    tax_pct_column: str = Field(default="tax_pct")
    line_total_column: str = Field(default="line_total")


class LineTotalMismatchDetector:
    """`cross_field.line_total_mismatch` — flags rows where `line_total`
    does not equal `quantity × unit_price × (1 − discount_pct/100) × (1
    + tax_pct/100)`, recomputed from the row's own values.

    `supports()` always returns `True` (dataset-level):
    `DetectorSupportRequest` carries no `configuration`, so a possibly-
    overridden column name cannot be resolved before `run()` — a
    disclosed architectural constraint. When the five (possibly-
    overridden) role columns cannot all be resolved to existing
    `NUMERIC`-typed columns, `run()` returns `SUCCESS` with zero findings
    and one `DetectorWarning` rather than `FAILED`: a dataset lacking
    this exact schema is a legitimate "not applicable" outcome.
    """

    metadata = DetectorMetadata(
        detector_id="cross_field.line_total_mismatch",
        version="1",
        name="Line-total mismatch",
        category=DetectorCategory.CROSS_FIELD,
        description=(
            "Flags rows where 'line_total' does not equal quantity x unit_price "
            "adjusted for discount/tax percentages, recomputed from the row's "
            "own values."
        ),
        applicable_inferred_types=(),
        required_profile_fields=(
            "column_profiles[].column.original_name",
            "column_profiles[].inferred_type",
        ),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Hardcoded to the standard sales-order column-naming convention "
            "(quantity/unit_price/discount_pct/tax_pct/line_total), overridable "
            "via configuration; a dataset using different names for the same "
            "concepts is not checked unless configured — no confirmed "
            "column-role context (CTX-01) exists yet.",
            "Recomputation assumes the fixed formula quantity x unit_price x "
            "(1 - discount_pct/100) x (1 + tax_pct/100) with a one-cent "
            "rounding tolerance; a dataset using a materially different "
            "pricing formula (e.g. tax before discount, compounding, per-line "
            "fees) would produce false positives.",
        ),
    )
    config_schema: type[BaseModel] = _LineTotalMismatchConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level; required-columns check happens in run().
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        config = _LineTotalMismatchConfig.model_validate(request.configuration)

        by_lowered_name: dict[str, tuple[ColumnReference, InferredColumnType]] = {
            profile.column.original_name.strip().lower(): (profile.column, profile.inferred_type)
            for profile in request.dataset_profile.column_profiles
        }

        role_names = {
            "quantity": config.quantity_column,
            "unit_price": config.unit_price_column,
            "discount_pct": config.discount_pct_column,
            "tax_pct": config.tax_pct_column,
            "line_total": config.line_total_column,
        }

        resolved: dict[str, ColumnReference] = {}
        for role, configured_name in role_names.items():
            match = by_lowered_name.get(configured_name.strip().lower())
            if match is None or match[1] is not InferredColumnType.NUMERIC:
                return DetectorRunResult(
                    detector_id=self.metadata.detector_id,
                    detector_version=self.metadata.version,
                    status=DetectorRunStatus.SUCCESS,
                    findings=(),
                    evidence=(),
                    warnings=(
                        DetectorWarning(
                            code="cross_field.required_columns_not_found",
                            message=(
                                f"{self.metadata.detector_id}: configured '{role}' column "
                                f"'{configured_name}' was not found as a NUMERIC column."
                            ),
                        ),
                    ),
                    execution_metrics=ExecutionMetrics(duration_ms=0),
                )
            resolved[role] = match[0]

        affected_indices: list[int] = []
        for index, row in enumerate(request.rows):
            raw_values: dict[str, float] = {}
            skip = False
            for role, column in resolved.items():
                value = row.get(column.internal_key)
                if not isinstance(value, str) or not value:
                    skip = True
                    break
                try:
                    raw_values[role] = float(value.strip())
                except ValueError:
                    skip = True
                    break
            if skip:
                continue

            expected = (
                raw_values["quantity"]
                * raw_values["unit_price"]
                * (1 - raw_values["discount_pct"] / 100)
                * (1 + raw_values["tax_pct"] / 100)
            )
            if round(abs(raw_values["line_total"] - expected), 2) > _LINE_TOTAL_TOLERANCE:
                affected_indices.append(index)

        if not affected_indices:
            return DetectorRunResult(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                status=DetectorRunStatus.SUCCESS,
                findings=(),
                evidence=(),
                warnings=(),
                execution_metrics=ExecutionMetrics(duration_ms=0),
            )

        affected_row_references = tuple(request.row_references[index] for index in affected_indices)
        affected_columns = tuple(resolved[role] for role in role_names)
        evidence_id = "cross_field.line_total_mismatch.evidence"
        finding_evidence = Evidence(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.CROSS_FIELD_COMPARISON,
            calculation_version="1",
            structured_payload={
                "tolerance": _LINE_TOTAL_TOLERANCE,
                "mismatch_count": len(affected_indices),
            },
            affected_columns=affected_columns,
            affected_row_references=affected_row_references,
            scope=SamplingScope.FULL,
            display_safe_summary=(
                f"{len(affected_indices)} row(s) have a 'line_total' that does not "
                "match the recomputed quantity/unit_price/discount/tax formula."
            ),
        )
        finding = FindingCandidate(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            category=self.metadata.category,
            severity=Severity.HIGH,
            confidence=1.0,
            calculated_observation=(
                f"{len(affected_indices)} row(s) have a 'line_total' that does not "
                "match quantity x unit_price x (1 - discount_pct/100) x "
                "(1 + tax_pct/100)."
            ),
            affected_columns=affected_columns,
            affected_row_references=affected_row_references,
            evidence_ids=(evidence_id,),
            default_remediation_template_key=None,
            default_validation_rule_template_key=None,
        )

        return DetectorRunResult(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            status=DetectorRunStatus.SUCCESS,
            findings=(finding,),
            evidence=(finding_evidence,),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=0),
        )
