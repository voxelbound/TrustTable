"""One SQLAlchemy 2 ORM model, `AnalysisRecord` (`DB-01`).

One row per analysis (recorded assumption 1, `WP-074`): scalar,
indexable columns for `analysis_id`/`state`/the four terminal
timestamps — exactly what the startup reconciliation query
(`reconciliation.py`) and the `analyses` table's own primary-key lookup
need — and JSON columns for the rest of `analysis.service.Analysis`'s
own field list (`docs/architecture.md` §8's explicit "large validated
structures may be stored as JSON" permission). Raw `content` bytes are a
`LargeBinary` column in this same table (recorded assumption 2) rather
than a separate file.

This model stores data only — no business behavior, no invariant
enforcement (`docs/architecture.md` §3: "persistence models do not
define business behavior"). Every invariant stays in
`analysis.service.Analysis.__post_init__`; `serializers.py` reuses it
directly on every read.

Timestamp/state columns intentionally store the same generic-codec
`serializers.encode`/`decode` representation as the JSON columns
(`String` holding an ISO-8601 instant, not a native SQLAlchemy
`DateTime`): SQLite has no real datetime type, and SQLAlchemy's
`DateTime` column silently drops `tzinfo` on that backend — this project
requires the exact original timezone-aware `datetime` back
(`analysis.service.Analysis`'s own fields are always `datetime.now(UTC)`
in practice, but nothing here assumes that). `state` stays a plain
`String` (the enum's own `.value`) so the reconciliation query can filter
on it directly with a simple `NOT IN`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every persistence ORM model in this package."""


class AnalysisRecord(Base):
    """One persisted `analysis.service.Analysis` (`DB-01`)."""

    __tablename__ = "analyses"
    __table_args__ = (
        Index("ix_analyses_state", "state"),
        Index("ix_analyses_retry_source_analysis_id", "retry_source_analysis_id"),
    )

    analysis_id: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, nullable=False)

    created_at: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    failed_at: Mapped[str | None] = mapped_column(String, nullable=True)
    cancelled_at: Mapped[str | None] = mapped_column(String, nullable=True)

    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    dataset_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    security_exposure_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    dataset_profile_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    findings_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    priority_scores_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    trust_assessment_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    guided_questions_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    rules_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    """User-defined validation rules (`RULE-01` slice 1) -- `NULL` for
    every analysis persisted before this column existed
    (`0003_add_rules_json.py`), decoded as an empty tuple by
    `store._row_to_analysis`, matching `retry_source_analysis_id`'s own
    nullable-additive-column precedent (`0002`)."""

    finding_reviews_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    """Per-finding review state (`REV-01`, `WP-083`), keyed by
    `finding_id` -- `NULL` for every analysis persisted before this
    column existed (`0004_add_finding_reviews_json.py`), decoded as an
    empty mapping by `store._row_to_analysis`, matching `rules_json`'s
    own nullable-additive-column precedent (`0003`)."""

    ai_enrichment_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    """Counters of optional AI enrichment calls (`EXP-01` slice 4,
    `WP-087`) -- `NULL` for every analysis persisted before this column
    existed (`0006_add_ai_enrichment_json.py`), decoded as `None`, i.e.
    *not recorded*, by `store._row_to_analysis`; never as a zero record."""

    context_version: Mapped[int] = mapped_column(nullable=False, default=0)
    context_finalized: Mapped[bool] = mapped_column(nullable=False, default=False)

    retry_source_analysis_id: Mapped[str | None] = mapped_column(String, nullable=True)
    """The originating `analysis_id` when this row is a retry (`JOB-01`
    slice 2, `WP-076`, `DEC-013`) -- `NULL` for every analysis that is not
    itself a retry, including every row persisted before this column
    existed (`0002_add_retry_source_analysis_id.py`)."""


class ConfirmedRelationshipVersionRecord(Base):
    """One immutable version of one user-stated relationship
    (`DET-03`, `docs/decision-log.md` D-059).

    Stores data only; the rules live in `domain.confirmed_relationship`.
    Rows are inserted once and never updated or individually deleted; they
    end with their analysis. The unique key is the backstop that makes two
    writers holding the same expected version impossible to both succeed.
    No column name and no cell value is stored, only the internal key and
    ordinal of each role's `ColumnReference`.
    """

    __tablename__ = "confirmed_relationship_versions"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "relationship_id",
            "version",
            name="uq_confirmed_relationship_version",
        ),
        Index("ix_confirmed_relationship_versions_analysis_id", "analysis_id"),
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    analysis_id: Mapped[str] = mapped_column(String, nullable=False)
    relationship_id: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    transition: Mapped[str] = mapped_column(String, nullable=False)
    start_key: Mapped[str] = mapped_column(String, nullable=False)
    start_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    end_key: Mapped[str] = mapped_column(String, nullable=False)
    end_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[str] = mapped_column(String, nullable=False)


class ReportRecord(Base):
    """One immutable rendered report snapshot (`EXP-01` slice 3, `WP-086`).

    Stores data only. `seq` is a monotonic insertion order so listing is
    in creation order; `report_id` is the public identifier. `markdown` is
    the exact rendered text and `content_sha256` its digest -- rows are
    inserted once and never updated.
    """

    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_analysis_id", "analysis_id"),)

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    analysis_id: Mapped[str] = mapped_column(String, nullable=False)
    generated_at: Mapped[str] = mapped_column(String, nullable=False)
    include_dismissed: Mapped[bool] = mapped_column(nullable=False)
    include_technical_appendix: Mapped[bool] = mapped_column(nullable=False)
    include_bounded_examples: Mapped[bool] = mapped_column(nullable=False)
    schema_version: Mapped[str] = mapped_column(String, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String, nullable=False)
