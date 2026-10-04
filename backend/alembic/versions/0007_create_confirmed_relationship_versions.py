"""create confirmed_relationship_versions table

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-04

Additive-only migration (`DET-03`, confirmed-relationship foundation):
creates the `confirmed_relationship_versions` table holding immutable
versions of user-stated relationships. No existing table, column or row is
touched. Reversible: `downgrade` drops the table, restoring the exact `0006`
schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "confirmed_relationship_versions",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_id", sa.String(), nullable=False),
        sa.Column("relationship_id", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("transition", sa.String(), nullable=False),
        sa.Column("start_key", sa.String(), nullable=False),
        sa.Column("start_ordinal", sa.Integer(), nullable=False),
        sa.Column("end_key", sa.String(), nullable=False),
        sa.Column("end_ordinal", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "analysis_id",
            "relationship_id",
            "version",
            name="uq_confirmed_relationship_version",
        ),
    )
    op.create_index(
        "ix_confirmed_relationship_versions_analysis_id",
        "confirmed_relationship_versions",
        ["analysis_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_confirmed_relationship_versions_analysis_id",
        table_name="confirmed_relationship_versions",
    )
    op.drop_table("confirmed_relationship_versions")
