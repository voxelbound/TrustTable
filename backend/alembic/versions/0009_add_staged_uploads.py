"""add staged_uploads table

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-08

Additive-only migration (`UX-02`, `docs/decision-log.md` D-068): creates the
`staged_uploads` table that holds a chosen file's bytes temporarily, under the
SHA-256 digest of an opaque single-use reference, until Run consumes it, it is
discarded, or it expires. No existing table or column is touched. Reversible:
`downgrade` drops the table, restoring the exact `0008` schema (staged files
are temporary by design, so nothing durable is lost).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "staged_uploads",
        sa.Column("ref_digest", sa.String(), primary_key=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("format", sa.String(), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_staged_uploads_expires_at", "staged_uploads", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_staged_uploads_expires_at", table_name="staged_uploads")
    op.drop_table("staged_uploads")
