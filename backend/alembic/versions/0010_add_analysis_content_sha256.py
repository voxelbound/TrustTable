"""add analyses.content_sha256 and the lookup indexes

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09

Additive migration (`UX-03`, `docs/decision-log.md` D-069): adds the nullable
`analyses.content_sha256` column and two indexes (`content_sha256` for the
seen-before lookup, `created_at` for the recent-analyses list). Existing rows
are backfilled by hashing their stored `content` one row at a time, so the
lookup also recognises analyses created before this migration. No existing
column is changed. Reversible: `downgrade` drops the indexes and the column,
restoring the exact `0009` schema; the digest is derived data, so nothing
durable is lost.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("analyses") as batch:
        batch.add_column(sa.Column("content_sha256", sa.String(), nullable=True))
    bind = op.get_bind()
    ids = [row[0] for row in bind.execute(sa.text("SELECT analysis_id FROM analyses"))]
    for analysis_id in ids:
        content = bind.execute(
            sa.text("SELECT content FROM analyses WHERE analysis_id = :id"), {"id": analysis_id}
        ).scalar()
        if content is None:
            continue
        bind.execute(
            sa.text("UPDATE analyses SET content_sha256 = :digest WHERE analysis_id = :id"),
            {"digest": hashlib.sha256(bytes(content)).hexdigest(), "id": analysis_id},
        )
    op.create_index("ix_analyses_content_sha256", "analyses", ["content_sha256"])
    op.create_index("ix_analyses_created_at", "analyses", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_analyses_created_at", table_name="analyses")
    op.drop_index("ix_analyses_content_sha256", table_name="analyses")
    with op.batch_alter_table("analyses") as batch:
        batch.drop_column("content_sha256")
