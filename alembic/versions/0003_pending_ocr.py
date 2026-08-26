"""Migration 0003: OCR-pending file state (retryable scanned uploads)."""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_pending_ocr"
down_revision: str | None = "0002_core_business"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PG12+: allowed in a transaction as long as the new value is not used
    # within the same one — safe here.
    op.execute(
        "ALTER TYPE file_status ADD VALUE IF NOT EXISTS 'PENDING_OCR' AFTER 'FAILED'"
    )


def downgrade() -> None:
    # Postgres cannot remove enum values; leave the label in place.
    pass
