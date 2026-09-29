"""`SqlReportStore` (`EXP-01` slice 3): durable, insert-only storage of
immutable `ReportSnapshot` values in `models.ReportRecord`.

There is deliberately no update or delete: a stored report is a fixed
artifact. Reading re-runs `ReportSnapshot.__post_init__`, which verifies
the stored digest against the stored Markdown, so a corrupted row raises
instead of being served.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine

from ..exports.report_snapshot import ReportOptions, ReportSnapshot
from .database import build_session_factory
from .models import ReportRecord


def _to_snapshot(row: ReportRecord) -> ReportSnapshot:
    return ReportSnapshot(
        report_id=row.report_id,
        analysis_id=row.analysis_id,
        generated_at=datetime.fromisoformat(row.generated_at),
        options=ReportOptions(
            include_dismissed=row.include_dismissed,
            include_technical_appendix=row.include_technical_appendix,
            include_bounded_examples=row.include_bounded_examples,
        ),
        schema_version=row.schema_version,
        markdown=row.markdown,
        content_sha256=row.content_sha256,
    )


class SqlReportStore:
    """A durable, insert-only `ReportSnapshot` store."""

    def __init__(self, engine: Engine) -> None:
        self._session_factory = build_session_factory(engine)

    def add(self, snapshot: ReportSnapshot) -> None:
        with self._session_factory() as session:
            session.add(
                ReportRecord(
                    report_id=snapshot.report_id,
                    analysis_id=snapshot.analysis_id,
                    generated_at=snapshot.generated_at.isoformat(),
                    include_dismissed=snapshot.options.include_dismissed,
                    include_technical_appendix=snapshot.options.include_technical_appendix,
                    include_bounded_examples=snapshot.options.include_bounded_examples,
                    schema_version=snapshot.schema_version,
                    markdown=snapshot.markdown,
                    content_sha256=snapshot.content_sha256,
                )
            )
            session.commit()

    def get(self, analysis_id: str, report_id: str) -> ReportSnapshot | None:
        """The report, or `None` if unknown or belonging to another analysis."""
        with self._session_factory() as session:
            row = session.scalars(
                select(ReportRecord).where(
                    ReportRecord.report_id == report_id,
                    ReportRecord.analysis_id == analysis_id,
                )
            ).first()
            return _to_snapshot(row) if row is not None else None

    def list_for_analysis(self, analysis_id: str) -> Sequence[ReportSnapshot]:
        """Every report of the analysis, in creation order."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(ReportRecord)
                .where(ReportRecord.analysis_id == analysis_id)
                .order_by(ReportRecord.seq)
            ).all()
            return tuple(_to_snapshot(row) for row in rows)
