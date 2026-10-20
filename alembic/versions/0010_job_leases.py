"""Migration 0010: leases on processing jobs.

A worker that claims a batch or a file takes a lease: a token of its own and an expiry it keeps pushing back
while it works. Its writes only land while it still holds the token, so a worker that froze and woke up later
cannot overwrite the work of the one that took over. A lease that runs out (the worker died) lets another
worker claim the job; `attempts` counts claims, and a file interrupted too often is failed instead of retried
forever. See app/services/leases.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0010_job_leases"
down_revision: str | None = "0009_audit_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("upload_batches", "uploaded_files"):
        op.add_column(table, sa.Column("lease_token", UUID(as_uuid=True), nullable=True))
        op.add_column(table, sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
        # what the reaper scans for: jobs in progress whose lease may have run out
        op.create_index(f"ix_{table}_processing_lease", table, ["lease_expires_at"],
                        postgresql_where=sa.text("status = 'PROCESSING'"))
    op.add_column("uploaded_files", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("uploaded_files", "started_at")
    for table in ("upload_batches", "uploaded_files"):
        op.drop_index(f"ix_{table}_processing_lease", table_name=table)
        op.drop_column(table, "attempts")
        op.drop_column(table, "lease_expires_at")
        op.drop_column(table, "lease_token")
