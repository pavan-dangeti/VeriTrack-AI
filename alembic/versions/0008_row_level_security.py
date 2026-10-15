"""Migration 0008: PostgreSQL row-level security on every tenant table, as a second layer behind the
application's own org_id filters.

A row is visible, and may be written, only when its org_id equals the transaction's app.org_id setting, or
when a trusted internal step has set app.rls_bypass (see app/db/tenant.py).

A superuser or BYPASSRLS login ignores every policy, and hosts differ in what they give the login role. So
every application transaction switches to veritrack_app, a NOLOGIN role that can never bypass them, whatever
role it connected as. Creating it needs CREATEROLE (a managed database's owner role has it).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_row_level_security"
down_revision: str | None = "0007_organizations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = ("users", "employees", "employee_versions", "company_leaves", "upload_batches", "uploaded_files",
                 "extracted_rows", "analysis_runs", "violation_results", "generated_reports",
                 "approved_m365_domains", "audit_logs")
BYPASS = "current_setting('app.rls_bypass', true) = 'on'"
CURRENT_ORG = "nullif(current_setting('app.org_id', true), '')::uuid"


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'veritrack_app') THEN
            CREATE ROLE veritrack_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
          END IF;
        END $$
    """)
    op.execute("GRANT veritrack_app TO CURRENT_USER")   # lets the login role switch to it
    op.execute("GRANT USAGE ON SCHEMA public TO veritrack_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO veritrack_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO veritrack_app")
    # tables and sequences later migrations create
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public "
               "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO veritrack_app")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO veritrack_app")

    for table, column in [(t, "org_id") for t in TENANT_TABLES] + [("organizations", "id")]:
        rule = f"{BYPASS} OR {column} = {CURRENT_ORG}"
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({rule}) WITH CHECK ({rule})")


def downgrade() -> None:
    for table in (*TENANT_TABLES, "organizations"):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    # the role is cluster-wide and other databases on the server may use it, so only this database's grants go
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'veritrack_app') THEN
            ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM veritrack_app;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM veritrack_app;
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM veritrack_app;
            REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM veritrack_app;
            REVOKE USAGE ON SCHEMA public FROM veritrack_app;
          END IF;
        END $$
    """)
