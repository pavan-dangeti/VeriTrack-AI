"""Migration 0002: core business tables (uploads, repository, analysis)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID

revision: str = "0002_core_business"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUMS = {
    "batch_kind": ("EMPLOYEE_REPO", "GETS"),
    "batch_status": ("QUEUED", "PROCESSING", "COMPLETED", "FAILED"),
    "file_status": ("QUEUED", "PROCESSING", "DONE", "FAILED"),
    "analysis_status": ("RUNNING", "COMPLETED", "FAILED"),
    "email_status": ("PENDING", "SENT", "SKIPPED_NO_EMAIL", "ERROR"),
    "report_kind": ("SUMMARY_PDF", "EXCEL_3TAB"),
}


def _create_enum(name: str) -> None:
    values = ", ".join(f"'{v}'" for v in ENUMS[name])
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({values}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def upgrade() -> None:
    for name in ENUMS:
        _create_enum(name)

    batch_kind = ENUM(*ENUMS["batch_kind"], name="batch_kind", create_type=False)
    batch_status = ENUM(*ENUMS["batch_status"], name="batch_status", create_type=False)
    file_status = ENUM(*ENUMS["file_status"], name="file_status", create_type=False)
    analysis_status = ENUM(
        *ENUMS["analysis_status"], name="analysis_status", create_type=False
    )
    email_status = ENUM(*ENUMS["email_status"], name="email_status", create_type=False)
    report_kind = ENUM(*ENUMS["report_kind"], name="report_kind", create_type=False)

    op.create_table(
        "upload_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("manager_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", batch_kind, nullable=False),
        sa.Column("status", batch_status, nullable=False,
                  server_default=sa.text("'QUEUED'")),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("processed_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_files", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_batches_manager"),
    )
    op.create_index("ix_upload_batches_manager_id", "upload_batches", ["manager_id"])

    op.create_table(
        "uploaded_files",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("batch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("manager_id", UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("content_type_detected", sa.Text(), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.Text(), nullable=False),
        sa.Column("status", file_status, nullable=False, server_default=sa.text("'QUEUED'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("rows_extracted", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["upload_batches.id"], ondelete="CASCADE",
                                name="fk_files_batch"),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_files_manager"),
        sa.UniqueConstraint("storage_key", name="uq_files_storage_key"),
    )
    op.create_index("ix_uploaded_files_batch_id", "uploaded_files", ["batch_id"])
    op.create_index("ix_uploaded_files_manager_id", "uploaded_files", ["manager_id"])

    op.create_table(
        "extracted_rows",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("file_id", UUID(as_uuid=True), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("data", JSONB(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["file_id"], ["uploaded_files.id"], ondelete="CASCADE",
                                name="fk_rows_file"),
    )
    op.create_index("ix_extracted_rows_file_id", "extracted_rows", ["file_id"])

    op.create_table(
        "employees",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("manager_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_code", sa.Text(), nullable=False),
        sa.Column("current_version_id", UUID(as_uuid=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_employees_manager"),
        sa.UniqueConstraint("manager_id", "employee_code",
                            name="uq_employees_manager_code"),
    )
    op.create_index("ix_employees_manager_id", "employees", ["manager_id"])

    op.create_table(
        "employee_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("employee_id", UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("official_email", sa.Text(), nullable=True),
        sa.Column("personal_email", sa.Text(), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("changed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("change_source", sa.Text(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["employee_id"], ["employees.id"], ondelete="CASCADE",
                                name="fk_versions_employee"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL",
                                name="fk_versions_changed_by"),
        sa.UniqueConstraint("employee_id", "version_no",
                            name="uq_employee_versions_no"),
    )
    op.create_index("ix_employee_versions_employee_id", "employee_versions", ["employee_id"])

    # circular-safe FK: employees.current_version_id -> employee_versions.id
    op.create_foreign_key("fk_employees_current_version", "employees",
                          "employee_versions", ["current_version_id"], ["id"],
                          ondelete="SET NULL")

    op.create_table(
        "analysis_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("batch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("manager_id", UUID(as_uuid=True), nullable=False),
        sa.Column("triggered_by", UUID(as_uuid=True), nullable=True),
        sa.Column("status", analysis_status, nullable=False),
        sa.Column("files_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("matched", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("violations", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("emails_sent", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("emails_missing", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("emails_errored", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_rows", JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["upload_batches.id"], ondelete="CASCADE",
                                name="fk_runs_batch"),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_runs_manager"),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"], ondelete="SET NULL",
                                name="fk_runs_triggered_by"),
        sa.UniqueConstraint("batch_id", name="uq_runs_batch"),
    )
    op.create_index("ix_analysis_runs_manager_id", "analysis_runs", ["manager_id"])
    op.create_index("ix_analysis_runs_batch_id", "analysis_runs", ["batch_id"])

    op.create_table(
        "violation_results",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("manager_id", UUID(as_uuid=True), nullable=False),
        sa.Column("employee_code", sa.Text(), nullable=False),
        sa.Column("employee_name", sa.Text(), nullable=True),
        sa.Column("customer_leave_value", sa.Text(), nullable=True),
        sa.Column("sacha_leave_value", sa.Text(), nullable=True),
        sa.Column("violation_reason", sa.Text(), nullable=False),
        sa.Column("email_to", sa.Text(), nullable=True),
        sa.Column("email_status", email_status, nullable=False,
                  server_default=sa.text("'PENDING'")),
        sa.Column("email_error", sa.Text(), nullable=True),
        sa.Column("graph_message_id", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE",
                                name="fk_violations_run"),
        sa.ForeignKeyConstraint(["manager_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_violations_manager"),
        sa.UniqueConstraint("run_id", "employee_code",
                            name="uq_violations_run_employee"),
    )
    op.create_index("ix_violation_results_run_id", "violation_results", ["run_id"])
    op.create_index("ix_violation_results_manager_id", "violation_results", ["manager_id"])

    op.create_table(
        "generated_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", UUID(as_uuid=True), nullable=False),
        sa.Column("kind", report_kind, nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("emailed_to", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["analysis_runs.id"], ondelete="CASCADE",
                                name="fk_reports_run"),
    )
    op.create_index("ix_generated_reports_run_id", "generated_reports", ["run_id"])


def downgrade() -> None:
    op.drop_table("generated_reports")
    op.drop_table("violation_results")
    op.drop_table("analysis_runs")
    op.drop_constraint("fk_employees_current_version", "employees", type_="foreignkey")
    op.drop_table("employee_versions")
    op.drop_table("employees")
    op.drop_table("extracted_rows")
    op.drop_table("uploaded_files")
    op.drop_table("upload_batches")
    for name in ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {name}")
