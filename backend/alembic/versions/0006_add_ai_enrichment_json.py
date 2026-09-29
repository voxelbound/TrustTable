"""add ai_enrichment_json column

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-29

Additive-only migration (`EXP-01` slice 4, `WP-087`): adds one nullable
`ai_enrichment_json` JSON column to the existing `analyses` table for
`analysis.service.Analysis.ai_enrichment` (counters of optional AI
enrichment calls). Every already-persisted row gets `NULL`, which
`persistence.store._row_to_analysis` decodes as `None`, meaning *not
recorded* -- deliberately not a zero record, so an older analysis is never
reported as having had no AI calls. Reversible: `downgrade` drops the
column, restoring the exact `0005` schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("ai_enrichment_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "ai_enrichment_json")
