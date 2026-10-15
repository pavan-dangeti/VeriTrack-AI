"""Migration 0007: organisations. Every tenant row belongs to one organisation.

Existing rows are moved into a single "Default organisation". org_id defaults to the current transaction's
tenant setting (app.org_id), so rows created inside a request or job are scoped without the code naming the
organisation; with no tenant set, the default is NULL and the NOT NULL constraint refuses the insert.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0007_organizations"
down_revision: str | None = "0006_timesheets_leaves"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_DEFAULT = "nullif(current_setting('app.org_id', true), '')::uuid"
# audit_logs stays nullable: a failed sign-in for an unknown e-mail belongs to no organisation
TENANT_TABLES = ("users", "employees", "employee_versions", "company_leaves", "upload_batches", "uploaded_files",
                 "extracted_rows", "analysis_runs", "violation_results", "generated_reports",
                 "approved_m365_domains", "audit_logs")


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("uq_organizations_name_lower", "organizations", [sa.text("LOWER(name)")], unique=True)

    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("org_id", UUID(as_uuid=True), nullable=True))
    op.execute("""
        INSERT INTO organizations (name)
        SELECT 'Default organisation' WHERE EXISTS (SELECT 1 FROM users)
    """)
    for table in TENANT_TABLES:
        op.execute(f"UPDATE {table} SET org_id = (SELECT id FROM organizations ORDER BY created_at LIMIT 1)")
    for table in TENANT_TABLES:
        op.alter_column(table, "org_id", nullable=(table == "audit_logs"),
                        server_default=sa.text(TENANT_DEFAULT))
        op.create_foreign_key(f"fk_{table}_org_id", table, "organizations", ["org_id"], ["id"])
        op.create_index(f"ix_{table}_org_id", table, ["org_id"])

    # one Master Admin per organisation (was: one in the whole database)
    op.drop_index("uq_users_single_master_admin", table_name="users")
    op.create_index("uq_users_master_admin_per_org", "users", ["org_id"], unique=True,
                    postgresql_where=sa.text("role = 'MASTER_ADMIN'"))

    # the role hierarchy now also requires the manager and the creator to be in the same organisation
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_user_role_hierarchy() RETURNS trigger AS $$
        DECLARE
          related_role user_role;
          related_org uuid;
        BEGIN
          IF NEW.role = 'HR' THEN
            IF NEW.manager_id IS NULL THEN
              RAISE EXCEPTION 'HR users must have manager_id';
            END IF;
            SELECT role, org_id INTO related_role, related_org FROM users WHERE id = NEW.manager_id;
            IF related_role IS DISTINCT FROM 'MANAGER' THEN
              RAISE EXCEPTION 'HR.manager_id must reference a MANAGER (found %)',
                COALESCE(related_role::text, 'NULL');
            END IF;
            IF related_org IS DISTINCT FROM NEW.org_id THEN
              RAISE EXCEPTION 'HR must be in the same organisation as their manager';
            END IF;
            SELECT role, org_id INTO related_role, related_org FROM users WHERE id = NEW.created_by;
            IF related_role IS DISTINCT FROM 'MANAGER' THEN
              RAISE EXCEPTION 'HR can only be created by a MANAGER (creator role: %)',
                COALESCE(related_role::text, 'NULL');
            END IF;
            IF related_org IS DISTINCT FROM NEW.org_id THEN
              RAISE EXCEPTION 'users can only be created inside the creator''s organisation';
            END IF;
          ELSIF NEW.role IN ('MANAGER', 'EXECUTIVE') THEN
            IF NEW.manager_id IS NOT NULL THEN
              RAISE EXCEPTION 'Only HR users may have manager_id';
            END IF;
            SELECT role, org_id INTO related_role, related_org FROM users WHERE id = NEW.created_by;
            IF related_role IS DISTINCT FROM 'MASTER_ADMIN' THEN
              RAISE EXCEPTION
                '% can only be created by the MASTER_ADMIN (creator role: %)',
                NEW.role, COALESCE(related_role::text, 'NULL');
            END IF;
            IF related_org IS DISTINCT FROM NEW.org_id THEN
              RAISE EXCEPTION 'users can only be created inside the creator''s organisation';
            END IF;
          ELSE  -- MASTER_ADMIN bootstrap row: created_by must be empty
            IF NEW.created_by IS NOT NULL THEN
              RAISE EXCEPTION 'MASTER_ADMIN cannot have created_by';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("DROP TRIGGER trg_user_role_hierarchy ON users")
    op.execute("""
        CREATE TRIGGER trg_user_role_hierarchy
        BEFORE INSERT OR UPDATE OF role, manager_id, created_by, org_id ON users
        FOR EACH ROW EXECUTE FUNCTION enforce_user_role_hierarchy()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_user_role_hierarchy ON users")
    op.execute("""
        CREATE TRIGGER trg_user_role_hierarchy
        BEFORE INSERT OR UPDATE OF role, manager_id, created_by ON users
        FOR EACH ROW EXECUTE FUNCTION enforce_user_role_hierarchy()
    """)
    op.drop_index("uq_users_master_admin_per_org", table_name="users")
    op.create_index("uq_users_single_master_admin", "users", ["role"], unique=True,
                    postgresql_where=sa.text("role = 'MASTER_ADMIN'"))
    for table in TENANT_TABLES:
        op.drop_index(f"ix_{table}_org_id", table_name=table)
        op.drop_constraint(f"fk_{table}_org_id", table, type_="foreignkey")
        op.drop_column(table, "org_id")
    op.drop_index("uq_organizations_name_lower", table_name="organizations")
    op.drop_table("organizations")
