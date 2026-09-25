"""Migration 0004: OCR review-flag state on employees + settings support."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_review_flags"
down_revision: str | None = "0003_pending_ocr"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("employees", sa.Column("needs_review", sa.Boolean(), nullable=False,
                                         server_default=sa.text("false")))
    op.add_column("employees", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("employees", sa.Column("ocr_confidence", sa.Float(), nullable=True))
    op.create_index("ix_employees_needs_review", "employees", ["needs_review"])


def downgrade() -> None:
    op.drop_index("ix_employees_needs_review", table_name="employees")
    op.drop_column("employees", "ocr_confidence")
    op.drop_column("employees", "review_note")
    op.drop_column("employees", "needs_review")
