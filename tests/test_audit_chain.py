"""The audit log is tamper-evident: every kind of change made directly in the database is caught, at the
entry where it was made, by the CLI and the admin endpoint.

Tampering goes through the database login role with row-level security bypassed: an attacker with database
access, not the application (which may only append, see test_the_application_can_only_append).
"""

import asyncio

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db.session import engine
from app.db.tenant import SYSTEM, tenant
from app.models.audit_log import AuditLog, AuditResult
from app.services import audit_chain, audit_service
from tests.conftest import open_session
from tests.helpers import admin

ENTRIES = 9   # the Master Admin's bootstrap entry plus TEST_1..TEST_8


@pytest.fixture
async def org(ma_user_id):
    async with open_session() as db:
        for i in range(1, ENTRIES):
            await audit_service.record(db, action=f"TEST_{i}", result=AuditResult.SUCCESS,
                                       actor_user_id=ma_user_id, metadata={"i": i})
        return (await db.execute(select(AuditLog.org_id).limit(1))).scalar_one()


async def _tamper(sql: str, **params) -> None:
    async with engine.begin() as conn:   # the login role, not veritrack_app
        await conn.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))
        await conn.execute(text(sql), params)


async def _report(org_id, expect_heads=None) -> audit_chain.ChainReport:
    with tenant(SYSTEM):
        async with open_session() as db:
            reports = await audit_chain.verify(db, expect_heads)
    return next(r for r in reports if r.org_id == org_id)


async def _id_of(seq: int) -> int:
    with tenant(SYSTEM):
        async with open_session() as db:
            return (await db.execute(select(AuditLog.id).where(AuditLog.chain_seq == seq,
                                                               AuditLog.org_id.is_not(None)))).scalar_one()


async def test_an_untouched_log_verifies(org):
    report = await _report(org)
    assert report.ok and report.entries == ENTRIES and report.head_seq == ENTRIES


async def test_concurrent_writers_build_one_gap_free_chain(org):
    async def write(i):
        async with open_session() as db:
            await audit_service.record(db, action="CONCURRENT", result=AuditResult.SUCCESS, metadata={"i": i})

    await asyncio.gather(*(write(i) for i in range(40)))
    report = await _report(org)
    assert report.ok and report.entries == ENTRIES + 40 and report.head_seq == ENTRIES + 40


REHASH_AS_NOTHING_HAPPENED = """
    UPDATE audit_logs SET action = 'NOTHING_HAPPENED',
      entry_hash = encode(sha256(convert_to(audit_log_canonical(org_id, chain_seq, prev_hash, timestamp,
        actor_user_id, 'NOTHING_HAPPENED', target_entity, target_id, ip_address, user_agent, result::text,
        metadata), 'UTF8')), 'hex')
    WHERE id = :id"""


@pytest.mark.parametrize(("change", "sql", "broken_at", "reason"), [
    ("action", "UPDATE audit_logs SET action = 'NOTHING_HAPPENED' WHERE id = :id", 4, "content does not match"),
    ("metadata", "UPDATE audit_logs SET metadata = '{\"i\": 99}' WHERE id = :id", 4, "content does not match"),
    ("timestamp", "UPDATE audit_logs SET timestamp = timestamp - interval '1 day' WHERE id = :id", 4,
     "content does not match"),
    ("actor", "UPDATE audit_logs SET actor_user_id = NULL WHERE id = :id", 4, "content does not match"),
    ("result", "UPDATE audit_logs SET result = 'DENIED' WHERE id = :id", 4, "content does not match"),
    # the attacker also recomputes the entry's own hash: the next entry no longer links to it
    ("action and its own hash", REHASH_AS_NOTHING_HAPPENED, 5, "does not link"),
    ("deleted entry", "DELETE FROM audit_logs WHERE id = :id", 5, "sequence jumps from 3 to 5"),
])
async def test_each_change_is_caught_where_it_was_made(org, change, sql, broken_at, reason):
    await _tamper(sql, id=await _id_of(4))
    report = await _report(org)
    assert not report.ok, f"{change} went unnoticed"
    assert report.first_break["seq"] == broken_at and reason in report.first_break["reason"], report.first_break


async def test_reordered_entries_are_caught(org):
    for step in ("UPDATE audit_logs SET chain_seq = 100000 WHERE org_id = :org AND chain_seq = 4",
                 "UPDATE audit_logs SET chain_seq = 4 WHERE org_id = :org AND chain_seq = 5",
                 "UPDATE audit_logs SET chain_seq = 5 WHERE org_id = :org AND chain_seq = 100000"):
        await _tamper(step, org=org)
    report = await _report(org)
    assert report.first_break["seq"] == 4 and "does not link" in report.first_break["reason"], report.first_break


async def test_a_forged_entry_inserted_in_the_middle_is_caught(org):
    """Entries 5.. move up one and a well-formed entry takes seat 5, hashed to link to entry 4."""
    await _tamper("ALTER TABLE audit_logs DISABLE TRIGGER trg_audit_log_chain")
    try:
        await _tamper("UPDATE audit_logs SET chain_seq = chain_seq + 1000 WHERE org_id = :org AND chain_seq >= 5",
                      org=org)
        await _tamper("UPDATE audit_logs SET chain_seq = chain_seq - 999 WHERE org_id = :org AND chain_seq > 1000",
                      org=org)
        await _tamper("""
            INSERT INTO audit_logs (org_id, action, result, timestamp, chain_seq, prev_hash, entry_hash)
            SELECT :org, 'FORGED', 'SUCCESS', now(), 5, entry_hash,
                   encode(sha256(convert_to(audit_log_canonical(:org, 5, entry_hash, now(), NULL, 'FORGED', NULL,
                     NULL, NULL, NULL, 'SUCCESS', NULL), 'UTF8')), 'hex')
              FROM audit_logs WHERE org_id = :org AND chain_seq = 4""", org=org)
    finally:
        await _tamper("ALTER TABLE audit_logs ENABLE TRIGGER trg_audit_log_chain")
    report = await _report(org)
    assert report.first_break["seq"] == 6 and "does not link" in report.first_break["reason"], report.first_break


async def test_removing_the_newest_entries_needs_a_recorded_head_to_be_caught(org):
    head = await _report(org)
    await _tamper("DELETE FROM audit_logs WHERE org_id = :org AND chain_seq > :seq", org=org, seq=ENTRIES - 2)
    assert (await _report(org)).ok   # what is left still links up
    report = await _report(org, {org: (head.head_seq, head.head_hash)})
    assert not report.ok and "no longer in the chain" in report.first_break["reason"]


async def test_a_full_rewrite_needs_a_recorded_head_to_be_caught(org):
    """With write access and the algorithm, an attacker can change an entry and re-hash every later one."""
    head = await _report(org)
    await _tamper("UPDATE audit_logs SET action = 'NOTHING_HAPPENED' WHERE id = :id", id=await _id_of(4))
    await _tamper("""
        DO $$ DECLARE r record; prev text := repeat('0', 64); BEGIN
          FOR r IN SELECT * FROM audit_logs WHERE org_id IS NOT NULL ORDER BY chain_seq LOOP
            UPDATE audit_logs SET prev_hash = prev, entry_hash = encode(sha256(convert_to(audit_log_canonical(
              r.org_id, r.chain_seq, prev, r.timestamp, r.actor_user_id, r.action, r.target_entity, r.target_id,
              r.ip_address, r.user_agent, r.result::text, r.metadata), 'UTF8')), 'hex')
            WHERE id = r.id RETURNING entry_hash INTO prev;
          END LOOP; END $$""")
    assert (await _report(org)).ok   # a consistent forgery
    report = await _report(org, {org: (head.head_seq, head.head_hash)})
    assert not report.ok and "no longer in the chain" in report.first_break["reason"]


async def test_the_application_can_only_append(org):
    for sql in ("UPDATE audit_logs SET action = 'X'", "DELETE FROM audit_logs", "TRUNCATE audit_logs"):
        async with open_session() as db:
            with pytest.raises(ProgrammingError, match="permission denied"):
                await db.execute(text(sql))
    assert (await _report(org)).ok


async def test_a_user_with_audit_history_cannot_be_deleted(org, ma_user_id):
    """The actor foreign key used to null out the user's entries, silently rewriting the log."""
    with pytest.raises(DBAPIError, match="foreign key"):
        await _tamper("DELETE FROM users WHERE id = :id", id=ma_user_id)


async def test_cli_reports_each_chain_and_fails_on_a_break(org, capsys):
    from app.cli import verify_audit_log

    assert await verify_audit_log([]) == 0
    head_line = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("OK"))
    head = head_line.rsplit("head ", 1)[1]
    assert head.startswith(f"{org}:{ENTRIES}:")
    assert await verify_audit_log([head]) == 0

    await _tamper("DELETE FROM audit_logs WHERE org_id = :org AND chain_seq = :seq", org=org, seq=ENTRIES)
    assert await verify_audit_log([]) == 0          # removing only the newest entry needs the head...
    assert await verify_audit_log([head]) == 1      # ...which catches it
    await _tamper("UPDATE audit_logs SET action = 'X' WHERE id = :id", id=await _id_of(2))
    assert await verify_audit_log([]) == 1
    assert f"BROKEN  {org}" in capsys.readouterr().out


async def test_admin_endpoint_verifies_the_organisations_chain_and_is_audited(client, org):
    ma = await admin(client)
    r = await client.get("/api/v1/audit-logs/verify", headers=ma)
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    head = r.json()["head"]

    r = await client.get("/api/v1/audit-logs/verify", headers=ma,
                         params={"expect_seq": head["seq"], "expect_hash": head["hash"]})
    assert r.json()["ok"] is True
    await _tamper("UPDATE audit_logs SET metadata = '{}' WHERE id = :id", id=await _id_of(3))
    body = (await client.get("/api/v1/audit-logs/verify", headers=ma)).json()
    assert body["ok"] is False and body["first_break"]["seq"] == 3

    async with open_session() as db:
        results = list(await db.scalars(select(AuditLog.result).where(
            AuditLog.action == audit_service.ACTION_AUDIT_VERIFIED).order_by(AuditLog.chain_seq)))
    assert results == [AuditResult.SUCCESS, AuditResult.SUCCESS, AuditResult.FAILURE]
    assert (await client.get("/api/v1/audit-logs/verify", headers=ma, params={"expect_seq": 3})).status_code == 422


async def test_entries_without_an_organisation_form_their_own_chain(client, org):
    for _ in range(3):   # failed sign-ins for an unknown e-mail belong to no organisation
        await client.post("/api/v1/auth/login", json={"email": "ghost@nowhere.example", "password": "Wrong!123456"})
    with tenant(SYSTEM):
        async with open_session() as db:
            reports = {r.org_id: r for r in await audit_chain.verify(db)}
            in_org = (await db.execute(select(func.count()).where(AuditLog.org_id == org))).scalar_one()
    assert reports[None].ok and reports[None].entries == 3
    assert reports[org].ok and reports[org].entries == in_org


def test_the_migration_chains_existing_entries_exactly_as_the_trigger_does():
    """Entries written before migration 0009 are chained by its backfill: downgrading drops the chain, and
    upgrading again must rebuild it hash for hash, per organisation, with the no-organisation chain apart."""
    import os

    from alembic.config import Config
    from sqlalchemy.ext.asyncio import create_async_engine

    from alembic import command

    async def run(steps=(), read=False):
        eng = create_async_engine(os.environ["DATABASE_URL"])
        try:
            async with eng.begin() as conn:
                await conn.execute(text("SELECT set_config('app.rls_bypass', 'on', true)"))
                for sql, params in steps:
                    await conn.execute(text(sql), params)
                if read:
                    rows = await conn.execute(text(
                        "SELECT id, org_id, chain_seq, prev_hash, entry_hash FROM audit_logs ORDER BY id"))
                    return [tuple(r) for r in rows]
        finally:
            await eng.dispose()

    one, two = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    entries = [one, None, two, one, None, one, two]   # interleaved, as real traffic is
    insert = ("INSERT INTO audit_logs (org_id, action, result, metadata) "
              "VALUES (CAST(:org AS uuid), :action, 'SUCCESS', CAST(:meta AS jsonb))")
    before = asyncio.run(run(
        [("INSERT INTO organizations (id, name) VALUES (CAST(:a AS uuid), 'One'), (CAST(:b AS uuid), 'Two')",
          {"a": one, "b": two})]
        + [(insert, {"org": o, "action": f"A{i}", "meta": f'{{"i": {i}}}'}) for i, o in enumerate(entries)],
        read=True))
    assert [r[2] for r in before] == [1, 1, 1, 2, 2, 3, 2]

    cfg = Config("alembic.ini")
    command.downgrade(cfg, "0008_row_level_security")
    try:
        command.upgrade(cfg, "head")
    finally:
        command.upgrade(cfg, "head")   # never leave the shared test database behind
    assert asyncio.run(run(read=True)) == before


async def test_python_renders_entries_exactly_as_the_database_does(ma_user_id):
    """The verifier rebuilds each entry's text itself; it must match the trigger's, byte for byte, on awkward
    input, or legitimate entries would fail verification."""
    awkward = [
        ("QUOTE\"BACKSLASH\\", "Mozilla/5.0 \"quoted\"\nnew line\ttab\x01ctrl", "2001:db8::1",
         {"z": 1, "a": [1.5, "é", None, True], "nested": {"k\"ey": "line\nbreak", "emoji": "🔒"}}),
        ("UNICODE_ÄÖÜ_日本", None, "203.0.113.7", {}),
        ("NULLS", None, None, None),
        ("NUMBERS", "", "10.0.0.1", {"big": 12345678901234567890, "neg": -0.25, "zero": 0, "list": []}),
    ]
    async with open_session() as db:
        for action, agent, ip, meta in awkward:
            await audit_service.record(db, action=action, result=AuditResult.DENIED, actor_user_id=ma_user_id,
                                       target_entity="t x", target_id="id/ ", ip_address=ip,
                                       user_agent=agent, metadata=meta)
        rows = (await db.execute(text("""
            SELECT org_id, chain_seq, prev_hash, timestamp, actor_user_id, action, target_entity, target_id,
                   ip_address::text, user_agent, result::text, metadata::text,
                   audit_log_canonical(org_id, chain_seq, prev_hash, timestamp, actor_user_id, action,
                                       target_entity, target_id, ip_address, user_agent, result::text, metadata)
              FROM audit_logs ORDER BY chain_seq"""))).all()
    assert len(rows) == len(awkward) + 1
    for row in rows:
        assert audit_chain.canonical(*row[:12]) == row[12]


async def test_a_redefined_canonical_function_cannot_hide_an_edit(org):
    """An attacker who can change the schema edits entry 4, then redefines audit_log_canonical() to render
    the entry's original text. The verifier does not use that function, so the edit still shows."""
    with tenant(SYSTEM):
        async with open_session() as db:
            original_text, entry_id = (await db.execute(text("""
                SELECT audit_log_canonical(org_id, chain_seq, prev_hash, timestamp, actor_user_id, action,
                                           target_entity, target_id, ip_address, user_agent, result::text, metadata),
                       id
                  FROM audit_logs WHERE org_id = :org AND chain_seq = 4"""), {"org": org})).one()
            definition = (await db.execute(text(
                "SELECT pg_get_functiondef('audit_log_canonical'::regproc)"))).scalar_one()
    lying = definition.replace("SELECT json_build_array(", (
        f"SELECT CASE WHEN seq = 4 AND org = '{org}' THEN $q${original_text}$q$ ELSE json_build_array(")
    ).replace(")::text", ")::text END", 1)
    assert lying != definition
    try:
        await _tamper(lying)
        await _tamper("UPDATE audit_logs SET action = 'NOTHING_HAPPENED' WHERE id = :id", id=entry_id)
        report = await _report(org)
        assert report.first_break["seq"] == 4 and "content does not match" in report.first_break["reason"]
    finally:
        await _tamper(definition)
