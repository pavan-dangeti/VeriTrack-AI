"""Verifies the audit log's hash chains (migration 0009).

The database trigger writes each entry's hash; this recomputes it here, in Python, from the entry as it is
stored now, so a change to any field, or a removed, inserted or reordered entry, shows up as the first entry
where the chain no longer holds. A chain whose newest entries were all removed, or that was rewritten in full
by someone with database write access, still links up: compare it with a head recorded earlier
(`expect_heads`) to catch that. See docs/threat-model.md.
"""

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

GENESIS = "0" * 64

# each entry's canonical text, rendered by the same SQL function the trigger hashed
_ENTRIES = text("""
    SELECT id, org_id, chain_seq, prev_hash, entry_hash,
           audit_log_canonical(org_id, chain_seq, prev_hash, timestamp, actor_user_id, action, target_entity,
                               target_id, ip_address, user_agent, result::text, metadata) AS canonical
      FROM audit_logs
     ORDER BY org_id NULLS FIRST, chain_seq
""")


@dataclass
class ChainReport:
    org_id: uuid.UUID | None
    entries: int = 0
    head_seq: int = 0
    head_hash: str = GENESIS
    # the first entry where the chain fails, and why; None when the whole chain holds
    first_break: dict | None = None

    @property
    def ok(self) -> bool:
        return self.first_break is None

    def as_dict(self) -> dict:
        return {"org_id": str(self.org_id) if self.org_id else None, "ok": self.ok, "entries": self.entries,
                "head": {"seq": self.head_seq, "hash": self.head_hash}, "first_break": self.first_break}


def _break_reason(report: ChainReport, seq: int, prev: str, stored: str, canonical: str) -> str | None:
    if seq != report.head_seq + 1:
        return f"sequence jumps from {report.head_seq} to {seq}: entries removed or reordered"
    if prev != report.head_hash:
        return "does not link to the previous entry: an entry before it was changed, removed or inserted"
    if hashlib.sha256(canonical.encode()).hexdigest() != stored:
        return "content does not match its hash: the entry was changed"
    return None


async def verify(db: AsyncSession, expect_heads: Mapping[uuid.UUID | None, tuple[int, str]] | None = None
                 ) -> list[ChainReport]:
    """Every chain the session can see (row-level security limits a request to its organisation's).
    expect_heads maps an organisation to a (seq, hash) recorded earlier, which must still be in its chain."""
    anchors = expect_heads or {}
    reports: dict[uuid.UUID | None, ChainReport] = {}
    anchor_found: dict[uuid.UUID | None, str] = {}
    # ponytail: one pass over the whole log; for very large logs, verify from a trusted checkpoint instead
    async for entry_id, org_id, seq, prev, stored, canonical in await db.stream(_ENTRIES):
        report = reports.setdefault(org_id, ChainReport(org_id))
        report.entries += 1
        if not report.ok:
            continue
        if reason := _break_reason(report, seq, prev, stored, canonical):
            report.first_break = {"seq": seq, "id": entry_id, "reason": reason}
            continue
        report.head_seq, report.head_hash = seq, stored
        if org_id in anchors and anchors[org_id][0] == seq:
            anchor_found[org_id] = stored
    for org_id, (seq, expected) in anchors.items():
        report = reports.setdefault(org_id, ChainReport(org_id))
        if report.ok and anchor_found.get(org_id) != expected:
            report.first_break = {"seq": seq, "id": None, "reason": (
                f"the recorded head (entry {seq}) is no longer in the chain: entries were removed or rewritten")}
    return list(reports.values())
