"""create app_settings table

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-11

Additive-only migration (`UX-08a`, `docs/decision-log.md` D-066 item 5): creates
the `app_settings` table that holds the allowlisted, typed, versioned stored
product settings. No existing table or column is touched. Reversible:
`downgrade` drops the table, restoring the exact `0011` schema; a stored setting
only ever refines a default (an explicit deployment value always wins), so
dropping it returns the product to its built-in behavior and loses no analysis
data.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
