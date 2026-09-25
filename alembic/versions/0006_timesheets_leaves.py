"""Migration 0006: GETS timesheet extraction metadata, company leave register,
violation details, and indexes for the hot read paths."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0006_timesheets_leaves"
down_revision: str | None = "0005_user_full_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE batch_kind ADD VALUE IF NOT EXISTS 'COMPANY_LEAVE'")

    op.add_column("uploaded_files", sa.Column("extraction_meta", JSONB, nullable=True))
    op.add_column("violation_results", sa.Column("details", JSONB, nullable=True))

    op.create_table(
        "company_leaves",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("manager_id", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("employee_code", sa.Text(), nullable=False),
        sa.Column("leave_date", sa.Date(), nullable=False),
        sa.Column("leave_type", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'MANUAL'")),
        sa.Column("batch_id", UUID(as_uuid=True),
                  sa.ForeignKey("upload_batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("manager_id", "employee_code", "leave_date",
                            name="uq_company_leaves_manager_code_date"),
    )
    op.create_index("ix_company_leaves_lookup", "company_leaves",
                    ["manager_id", "employee_code", "leave_date"])

    op.create_index("ix_upload_batches_manager_created", "upload_batches",
                    ["manager_id", sa.text("created_at DESC")])
    op.create_index("ix_extracted_rows_file_row", "extracted_rows", ["file_id", "row_index"])
    op.create_index("ix_extracted_rows_review", "extracted_rows", ["file_id"],
                    postgresql_where=sa.text("needs_review"))
    op.create_index("ix_uploaded_files_status", "uploaded_files", ["status"])


def downgrade() -> None:
    op.drop_index("ix_uploaded_files_status", table_name="uploaded_files")
    op.drop_index("ix_extracted_rows_review", table_name="extracted_rows")
    op.drop_index("ix_extracted_rows_file_row", table_name="extracted_rows")
    op.drop_index("ix_upload_batches_manager_created", table_name="upload_batches")
    op.drop_index("ix_company_leaves_lookup", table_name="company_leaves")
    op.drop_table("company_leaves")
    op.drop_column("violation_results", "details")
    op.drop_column("uploaded_files", "extraction_meta")
    # enum labels cannot be removed in Postgres; COMPANY_LEAVE stays
