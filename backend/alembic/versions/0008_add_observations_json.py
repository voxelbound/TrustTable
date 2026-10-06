"""add observations_json column

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-05

Additive-only migration (`DET-03` closure package 2, `WP-109`): adds one
nullable `observations_json` JSON column to the existing `analyses` table for
`analysis.service.Analysis.observations` (neutral `value_evidence`
observations). Every already-persisted row gets `NULL`, which
`persistence.store._row_to_analysis` decodes as an empty tuple, i.e. no
observations. Reversible: `downgrade` drops the column, restoring the exact
`0007` schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("observations_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "observations_json")
