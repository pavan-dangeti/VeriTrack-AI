# Threat model

What VeriTrack protects, from whom, how, and what it does not protect against. Each control names the code
and the test that checks it.

## Assets

| Asset | Why it matters |
|---|---|
| Employee records, timesheets, leave registers, reports | personal data about people who never signed up for the app |
| Accounts and sessions | an account reads and changes everything its role allows |
| The audit log | the record of who did what; worthless if it can be quietly edited |
| One organisation's data, kept from another's | a customer must never see another customer's employees |

## Who might attack, and how

| Attacker | Can | Main controls |
|---|---|---|
| Anonymous internet user | call public endpoints, guess passwords | login rate limits and lockout with no lockout oracle; every other endpoint needs a token |
| Signed-in user, wrong role | call endpoints their role should not reach | role table enforced by the API (`tests/test_permission_matrix.py`) |
| User of another organisation | send another organisation's ids, read lists and exports | row-level security on every tenant table (`tests/test_tenant_isolation.py`) |
| Insider with an admin account | change data, then try to hide it | append-only, hash-chained audit log (`tests/test_audit_chain.py`) |
| Someone with database write access (leaked credentials, a careless operator) | change any row directly | the hash chain shows where; a recorded head shows a full rewrite (below) |
| Malicious upload | crash or exploit the parsers, inject spreadsheet formulas | magic-byte and size checks, exports neutralise formulas, OCR off the event loop |

## The audit log

Every audit entry belongs to one chain, one per organisation (entries with no organisation, such as failed
sign-ins for unknown e-mails, form their own). A database trigger fills in each entry's place on insert, so
no code path can skip it (`alembic/versions/0009_audit_chain.py`):

- `chain_seq`: 1, 2, 3, … with no gaps;
- `prev_hash`: the previous entry's hash (64 zeros for the first);
- `entry_hash`: SHA-256 of the entry's canonical text, which includes `chain_seq` and `prev_hash`.

The application's database role may insert entries but not update, delete or truncate them, and a user with
audit history cannot be deleted (the foreign key used to null out their entries).

**Verifying.** `python -m app.cli verify-audit-log` checks every chain and exits 1 if any is broken; a Master
Admin can check their organisation's chain at `GET /api/v1/audit-logs/verify`, and that check is itself
audited. The verifier recomputes every hash in Python (`app/services/audit_chain.py`) from each entry's raw
fields, and reports the first entry where the chain fails, and why. It rebuilds the canonical text itself
instead of calling the database's `audit_log_canonical()`, which someone able to change the schema could
redefine to render an edited entry's original text (`test_a_redefined_canonical_function_cannot_hide_an_edit`);
it relies only on built-in casts, which a database owner cannot redefine.

| Change made directly in the database | Caught? | Test |
|---|---|---|
| Any field of an entry edited | yes, at that entry | `test_each_change_is_caught_where_it_was_made` |
| An entry edited and its own hash recomputed | yes, at the next entry | same |
| An entry deleted from the middle | yes, at the next entry (sequence gap) | same |
| Entries reordered | yes, where the order changes | `test_reordered_entries_are_caught` |
| A forged entry inserted in the middle | yes, at the entry after it | `test_a_forged_entry_inserted_in_the_middle_is_caught` |
| The newest entries deleted | only against a recorded head | `test_removing_the_newest_entries_needs_a_recorded_head_to_be_caught` |
| The whole chain recomputed after an edit | only against a recorded head | `test_a_full_rewrite_needs_a_recorded_head_to_be_caught` |
| A fake entry appended at the end | **no** | — |

**Recorded heads.** A hash chain proves the log is consistent with itself, not that it is the log that was
written: someone who can write to the database and knows the algorithm can delete the newest entries, or
recompute every hash after an edit. To catch that, record a chain's head (`ORG:SEQ:HASH`, printed by the CLI
and returned by the endpoint) somewhere the database's users cannot change, and check against it later:

```bash
python -m app.cli verify-audit-log --expect-head <org-id>:<seq>:<hash>
```

The app does not record heads anywhere outside the database itself; that is the operator's job (for example a
weekly copy into a ticket or a separate account).

**Not covered.** Appending a fake entry at the end is indistinguishable from a real one: anyone who can insert
rows can do it. The chain makes past entries tamper-evident, not new ones trustworthy.

## Other controls

- **Organisations.** PostgreSQL row-level security on every tenant table, forced so it binds the table owner
  too. Every transaction runs as `veritrack_app`, a role that can never bypass it, whatever role the app logs in
  as (the isolation suite passes logged in as a superuser).
- **Sessions.** Access tokens last 15 minutes; refresh tokens rotate, and reusing a revoked one (outside a
  30-second grace window for parallel tabs) signs the user out everywhere. The refresh cookie is `HttpOnly`,
  `Secure`, `SameSite=Strict`, with a CSRF token on cookie-authenticated calls.
- **Passwords.** bcrypt, cost 12, hashed off the event loop; lockout after repeated failures.
- **Transport.** The API refuses a production database connection without TLS; HSTS on responses.
- **Data retention.** Timesheet batches past the retention window are purged on request
  (`POST /api/v1/settings/purge-obsolete-data`).

## Known gaps

- Fake entries appended to the audit log are not detectable (above).
- Chain heads are not recorded outside the database automatically.
- Verifying reads a chain from its first entry: fine at this app's volume, slow for millions of entries
  (verifying from a trusted checkpoint would fix that).
- E-mail addresses and SSO domains are unique across organisations, so trying one reveals that it exists
  somewhere.
- Uploaded files are stored unencrypted by the app; encryption at rest is left to the disk or bucket.
- Verification is only as trustworthy as the machine and code running it: run the CLI from a checkout you
  trust, not from a host the attacker controls.
