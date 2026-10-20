"""Migration 0009: a tamper-evident audit log.

Each organisation's audit entries form a hash chain: entry n stores SHA-256(canonical(entry n), including
the hash of entry n-1) and a gap-free sequence number. A trigger fills these in on every insert, whatever
code path inserts, and serialises inserts per chain with an advisory lock. Changing, removing, inserting or
reordering an entry breaks the chain from that point on; `python -m app.cli verify-audit-log` and
GET /api/v1/audit-logs/verify recompute it. Entries with no organisation form their own chain.

The log is append-only for the application role, and deleting a user no longer rewrites their entries
(the actor foreign key was ON DELETE SET NULL; it now refuses the delete). See docs/threat-model.md.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_audit_chain"
down_revision: str | None = "0008_row_level_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The canonical form of an entry: a JSON array of its fields, in this order. The verifier hashes exactly this
# text (app/services/audit_chain.py), so changing it means re-hashing every chain.
CANONICAL = """
    CREATE OR REPLACE FUNCTION audit_log_canonical(
        org uuid, seq bigint, prev text, ts timestamptz, actor uuid, action text, target_entity text,
        target_id text, ip inet, user_agent text, result text, meta jsonb
    ) RETURNS text LANGUAGE sql IMMUTABLE AS $$
        SELECT json_build_array(
            org, seq, prev, to_char(ts AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'), actor, action,
            target_entity, target_id, ip::text, user_agent, result, meta
        )::text
    $$
"""

CHAIN_TRIGGER = """
    CREATE OR REPLACE FUNCTION audit_log_chain() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE
      last_seq bigint;
      last_hash text;
    BEGIN
      -- one writer per chain at a time; released when the inserting transaction ends
      PERFORM pg_advisory_xact_lock(hashtextextended('audit:' || coalesce(NEW.org_id::text, 'none'), 0));
      SELECT chain_seq, entry_hash INTO last_seq, last_hash FROM audit_logs
       WHERE org_id IS NOT DISTINCT FROM NEW.org_id ORDER BY chain_seq DESC LIMIT 1;
      NEW.chain_seq := coalesce(last_seq, 0) + 1;
      NEW.prev_hash := coalesce(last_hash, repeat('0', 64));
      NEW.entry_hash := encode(sha256(convert_to(audit_log_canonical(
          NEW.org_id, NEW.chain_seq, NEW.prev_hash, NEW.timestamp, NEW.actor_user_id, NEW.action,
          NEW.target_entity, NEW.target_id, NEW.ip_address, NEW.user_agent, NEW.result::text, NEW.metadata
      ), 'UTF8')), 'hex');
      RETURN NEW;
    END
    $$
"""


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("chain_seq", sa.BigInteger(), nullable=True))
    op.add_column("audit_logs", sa.Column("prev_hash", sa.Text(), nullable=True))
    op.add_column("audit_logs", sa.Column("entry_hash", sa.Text(), nullable=True))
    op.execute(CANONICAL)
    op.execute(CHAIN_TRIGGER)

    # chain the existing entries, oldest first
    op.execute("""
        DO $$
        DECLARE
          r record;
          prev text;
          cur_org uuid;
          seq bigint;
          started boolean := false;
        BEGIN
          FOR r IN SELECT * FROM audit_logs ORDER BY org_id NULLS FIRST, id LOOP
            IF NOT started OR r.org_id IS DISTINCT FROM cur_org THEN
              cur_org := r.org_id; seq := 0; prev := repeat('0', 64); started := true;
            END IF;
            seq := seq + 1;
            UPDATE audit_logs SET chain_seq = seq, prev_hash = prev,
              entry_hash = encode(sha256(convert_to(audit_log_canonical(
                r.org_id, seq, prev, r.timestamp, r.actor_user_id, r.action, r.target_entity, r.target_id,
                r.ip_address, r.user_agent, r.result::text, r.metadata), 'UTF8')), 'hex')
             WHERE id = r.id
             RETURNING entry_hash INTO prev;
          END LOOP;
        END $$
    """)
    for column in ("chain_seq", "prev_hash", "entry_hash"):
        op.alter_column("audit_logs", column, nullable=False)
    op.create_index("uq_audit_logs_chain", "audit_logs",
                    [sa.text("coalesce(org_id, '00000000-0000-0000-0000-000000000000'::uuid)"), "chain_seq"],
                    unique=True)
    op.execute("""
        CREATE TRIGGER trg_audit_log_chain BEFORE INSERT ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_log_chain()
    """)

    # append-only for the application
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM veritrack_app")
    op.drop_constraint("fk_audit_logs_actor", "audit_logs", type_="foreignkey")
    op.create_foreign_key("fk_audit_logs_actor", "audit_logs", "users", ["actor_user_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_audit_logs_actor", "audit_logs", type_="foreignkey")
    op.create_foreign_key("fk_audit_logs_actor", "audit_logs", "users", ["actor_user_id"], ["id"],
                          ondelete="SET NULL")
    op.execute("GRANT UPDATE, DELETE ON audit_logs TO veritrack_app")
    op.execute("DROP TRIGGER trg_audit_log_chain ON audit_logs")
    op.drop_index("uq_audit_logs_chain", table_name="audit_logs")
    op.execute("DROP FUNCTION audit_log_chain()")
    op.execute("DROP FUNCTION audit_log_canonical(uuid, bigint, text, timestamptz, uuid, text, text, text, inet, "
               "text, text, jsonb)")
    for column in ("entry_hash", "prev_hash", "chain_seq"):
        op.drop_column("audit_logs", column)
