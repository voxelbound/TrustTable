"""create reports table

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-29

Additive-only migration (`EXP-01` slice 3, `WP-086`): creates the
`reports` table holding immutable rendered report snapshots. No existing
table, column or row is touched. Reversible: `downgrade` drops the table,
restoring the exact `0004` schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.String(), nullable=False, unique=True),
        sa.Column("analysis_id", sa.String(), nullable=False),
        sa.Column("generated_at", sa.String(), nullable=False),
        sa.Column("include_dismissed", sa.Boolean(), nullable=False),
        sa.Column("include_technical_appendix", sa.Boolean(), nullable=False),
        sa.Column("include_bounded_examples", sa.Boolean(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(), nullable=False),
    )
    op.create_index("ix_reports_analysis_id", "reports", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_analysis_id", table_name="reports")
    op.drop_table("reports")
