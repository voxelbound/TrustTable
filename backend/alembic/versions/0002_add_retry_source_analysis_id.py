"""add retry_source_analysis_id column

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26

Additive-only migration (`JOB-01` slice 2, `WP-076`, `DEC-013`): adds one
nullable, indexed `retry_source_analysis_id` column to the existing
`analyses` table. No existing column, constraint, or row is touched --
every already-persisted row gets `NULL` (not a retry) for the new column,
matching `analysis.service.Analysis.retry_source_analysis_id`'s own
`None` default exactly. Reversible: `downgrade` drops the index then the
column, restoring the exact `0001` schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyses", sa.Column("retry_source_analysis_id", sa.String(), nullable=True)
    )
    op.create_index(
        "ix_analyses_retry_source_analysis_id", "analyses", ["retry_source_analysis_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_analyses_retry_source_analysis_id", table_name="analyses")
    op.drop_column("analyses", "retry_source_analysis_id")
