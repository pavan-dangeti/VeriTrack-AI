"""Migration 0005: optional display name on users (email remains the identity)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_user_full_name"
down_revision: str | None = "0004_review_flags"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("full_name", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "full_name")
