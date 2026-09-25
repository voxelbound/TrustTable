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

from sqlalchemy import JSON, Index, LargeBinary, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for every persistence ORM model in this package."""


class AnalysisRecord(Base):
    """One persisted `analysis.service.Analysis` (`DB-01`)."""

    __tablename__ = "analyses"
    __table_args__ = (Index("ix_analyses_state", "state"),)

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

    context_version: Mapped[int] = mapped_column(nullable=False, default=0)
    context_finalized: Mapped[bool] = mapped_column(nullable=False, default=False)
