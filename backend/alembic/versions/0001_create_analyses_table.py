"""create analyses table

Revision ID: 0001
Revises:
Create Date: 2026-09-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("analysis_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.Column("failed_at", sa.String(), nullable=True),
        sa.Column("cancelled_at", sa.String(), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("dataset_json", sa.JSON(), nullable=False),
        sa.Column("security_exposure_json", sa.JSON(), nullable=False),
        sa.Column("dataset_profile_json", sa.JSON(), nullable=True),
        sa.Column("findings_json", sa.JSON(), nullable=False),
        sa.Column("priority_scores_json", sa.JSON(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("trust_assessment_json", sa.JSON(), nullable=True),
        sa.Column("failure_json", sa.JSON(), nullable=True),
        sa.Column("context_json", sa.JSON(), nullable=True),
        sa.Column("guided_questions_json", sa.JSON(), nullable=False),
        sa.Column("context_version", sa.Integer(), nullable=False),
        sa.Column("context_finalized", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("analysis_id"),
    )
    op.create_index("ix_analyses_state", "analyses", ["state"])


def downgrade() -> None:
    # Downgrade migrations are not implemented for the initial revision
    # (recorded assumption 5, `WP-074`): `docs/testing-strategy.md` §4's
    # "downgrade only when explicitly supported" — nothing has explicitly
    # requested downgrade support yet.
    raise NotImplementedError("downgrade is not supported for revision 0001")
