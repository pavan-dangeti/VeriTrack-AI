"""VeriTrack AI foundation schema.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-01-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM, INET, JSONB, UUID

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_VALUES = {
    "user_role": ("MASTER_ADMIN", "EXECUTIVE", "MANAGER", "HR"),
    "auth_type": ("M365", "PASSWORD"),
    "audit_result": ("SUCCESS", "FAILURE", "DENIED"),
}


def _create_enum(name: str) -> None:
    values = ", ".join(f"'{v}'" for v in ENUM_VALUES[name])
    # Idempotent per Postgres best practices (no ADD CONSTRAINT/CREATE TYPE IF NOT EXISTS).
    op.execute(
        f"DO $$ BEGIN CREATE TYPE {name} AS ENUM ({values}); "
        f"EXCEPTION WHEN duplicate_object THEN NULL; END $$;"
    )


def upgrade() -> None:
    # --- Enum types -----------------------------------------------------------
    for name in ENUM_VALUES:
        _create_enum(name)
    user_role = ENUM(*ENUM_VALUES["user_role"], name="user_role", create_type=False)
    auth_type = ENUM(*ENUM_VALUES["auth_type"], name="auth_type", create_type=False)
    audit_result = ENUM(
        *ENUM_VALUES["audit_result"], name="audit_result", create_type=False
    )

    # --- users ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("role", user_role, nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("auth_type", auth_type, nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("manager_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(auth_type = 'PASSWORD') = (password_hash IS NOT NULL)",
            name="chk_users_password_auth",
        ),
        sa.CheckConstraint(
            "role <> 'HR' OR manager_id IS NOT NULL",
            name="chk_users_hr_has_manager",
        ),
    )
    op.create_index("ix_users_manager_id", "users", ["manager_id"])
    op.create_index("ix_users_created_by", "users", ["created_by"])
    # Case-insensitive unique email without requiring the citext extension.
    op.create_index("uq_users_email_lower", "users", [sa.text("LOWER(email)")],
                    unique=True)
    # DB-level guarantee: never more than one Master Admin.
    op.create_index(
        "uq_users_single_master_admin",
        "users",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'MASTER_ADMIN'"),
    )
    op.create_foreign_key("fk_users_manager_id", "users", "users",
                          ["manager_id"], ["id"])
    op.create_foreign_key("fk_users_created_by", "users", "users",
                          ["created_by"], ["id"])

    # --- Role hierarchy enforcement trigger -------------------------------------
    # asyncpg cannot run multiple statements per execute; keep each DDL atomic.
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_user_role_hierarchy() RETURNS trigger AS $$
        DECLARE
          related_role user_role;
        BEGIN
          IF NEW.role = 'HR' THEN
            IF NEW.manager_id IS NULL THEN
              RAISE EXCEPTION 'HR users must have manager_id';
            END IF;
            SELECT role INTO related_role FROM users WHERE id = NEW.manager_id;
            IF related_role IS DISTINCT FROM 'MANAGER' THEN
              RAISE EXCEPTION 'HR.manager_id must reference a MANAGER (found %)',
                COALESCE(related_role::text, 'NULL');
            END IF;
            SELECT role INTO related_role FROM users WHERE id = NEW.created_by;
            IF related_role IS DISTINCT FROM 'MANAGER' THEN
              RAISE EXCEPTION 'HR can only be created by a MANAGER (creator role: %)',
                COALESCE(related_role::text, 'NULL');
            END IF;
          ELSIF NEW.role IN ('MANAGER', 'EXECUTIVE') THEN
            IF NEW.manager_id IS NOT NULL THEN
              RAISE EXCEPTION 'Only HR users may have manager_id';
            END IF;
            SELECT role INTO related_role FROM users WHERE id = NEW.created_by;
            IF related_role IS DISTINCT FROM 'MASTER_ADMIN' THEN
              RAISE EXCEPTION
                '% can only be created by the MASTER_ADMIN (creator role: %)',
                NEW.role, COALESCE(related_role::text, 'NULL');
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
    op.execute("""
        CREATE TRIGGER trg_user_role_hierarchy
        BEFORE INSERT OR UPDATE OF role, manager_id, created_by ON users
        FOR EACH ROW EXECUTE FUNCTION enforce_user_role_hierarchy()
    """)

    # --- audit_logs ---------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_entity", sa.String(length=100), nullable=True),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("ip_address", INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("result", audit_result, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"],
                                ondelete="SET NULL", name="fk_audit_logs_actor"),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_timestamp_desc", "audit_logs",
                    [sa.text("timestamp DESC")])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    # --- approved_m365_domains ------------------------------------------------------
    op.create_table(
        "approved_m365_domains",
        sa.Column("domain", sa.Text(), primary_key=True),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL",
                                name="fk_m365_domains_created_by"),
    )

    # --- refresh_tokens --------------------------------------------------------------
    op.create_table(
        "refresh_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_jti", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE",
                                name="fk_refresh_tokens_user"),
        sa.UniqueConstraint("jti", name="uq_refresh_tokens_jti"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
    op.drop_table("approved_m365_domains")
    op.drop_table("audit_logs")
    op.execute("DROP TRIGGER IF EXISTS trg_user_role_hierarchy ON users")
    op.execute("DROP FUNCTION IF EXISTS enforce_user_role_hierarchy()")
    op.drop_table("users")
    for name in ENUM_VALUES:
        op.execute(f"DROP TYPE IF EXISTS {name}")
