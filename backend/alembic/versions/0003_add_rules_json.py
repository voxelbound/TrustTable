"""add rules_json column

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28

Additive-only migration (`RULE-01` slice 1, `WP-078`): adds one nullable
`rules_json` JSON column to the existing `analyses` table for
`analysis.service.Analysis.rules` (`domain.rules.ValidationRule`, each
carrying its own latest `RuleExecutionResult`). No existing column,
constraint, or row is touched -- every already-persisted row gets `NULL`,
decoded as an empty tuple by `persistence.store._row_to_analysis`
(matching `retry_source_analysis_id`'s own nullable-additive-column
precedent, `0002`). No index: rules are read as part of the whole
analysis row, never queried on their own column. Reversible: `downgrade`
drops the column, restoring the exact `0002` schema.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("rules_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "rules_json")
