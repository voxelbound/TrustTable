"""create finding_enrichments table

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-10

Additive-only migration (`UX-05b`, `docs/decision-log.md` D-066 item 7): creates
the `finding_enrichments` table that holds one persisted AI enrichment per
analysis and finding -- its state, the digest of the binding it was produced
under, the disclosure flags and, only for an accepted result, the validated
explanation. No existing table or column is touched. Reversible: `downgrade`
drops the table, restoring the exact `0010` schema; a saved enrichment is
derived from the analysis and can be requested again, so nothing durable is
lost.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "finding_enrichments",
        sa.Column("analysis_id", sa.String(), nullable=False),
        sa.Column("finding_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("binding_digest", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("ai_call_status", sa.String(), nullable=False),
        sa.Column("evidence_sent_to_model", sa.Boolean(), nullable=False),
        sa.Column("confirmed_context_sent_to_model", sa.Boolean(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("analysis_id", "finding_id"),
    )
    op.create_index("ix_finding_enrichments_status", "finding_enrichments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_finding_enrichments_status", table_name="finding_enrichments")
    op.drop_table("finding_enrichments")
