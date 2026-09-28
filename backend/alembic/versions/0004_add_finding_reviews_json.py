"""add finding_reviews_json column

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-28

Additive-only migration (`REV-01`, `WP-083`): adds one nullable
`finding_reviews_json` JSON column to the existing `analyses` table for
`analysis.service.Analysis.finding_reviews` (`domain.review.FindingReview`,
keyed by `finding_id`). No existing column, constraint, or row is
touched -- every already-persisted row gets `NULL`, decoded as an empty
mapping by `persistence.store._row_to_analysis` (matching `rules_json`'s
own nullable-additive-column precedent, `0003`). No index: reviews are
read as part of the whole analysis row, never queried on their own
column. Reversible: `downgrade` drops the column, restoring the exact
`0003` schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("finding_reviews_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "finding_reviews_json")
