"""Which organisation the current request or job acts for.

PostgreSQL row-level security (migration 0008) only shows rows whose org_id equals the transaction's
`app.org_id` setting. A context variable holds the tenant for the current task, and a session hook copies it
into every transaction as it begins, so it survives the commits services make and never leaks between
concurrent requests (each runs in its own task). With no tenant set, queries see no tenant rows at all.

Every transaction also runs as veritrack_app (migration 0008), a role that cannot bypass row-level security,
so isolation does not depend on how the host configured the login role.

SYSTEM is for trusted internal steps that must look across organisations before the tenant is known:
resolving the signed-in user, sign-in itself, recovery of interrupted jobs, and the CLI.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import event, text
from sqlalchemy.orm import Session

SYSTEM = "system"

_tenant: ContextVar[uuid.UUID | str | None] = ContextVar("tenant", default=None)


def current() -> uuid.UUID | str | None:
    return _tenant.get()


def set_tenant(value: uuid.UUID | str | None) -> None:
    """For a request: the value lasts until the request's task ends."""
    _tenant.set(value)


@contextmanager
def tenant(value: uuid.UUID | str | None) -> Iterator[None]:
    """For a block of work: the previous tenant is restored afterwards. Start a new transaction inside it
    (commit or open a new session first), since the setting is applied when a transaction begins."""
    token = _tenant.set(value)
    try:
        yield
    finally:
        _tenant.reset(token)


@event.listens_for(Session, "after_begin")
def _apply_tenant(session, transaction, connection) -> None:
    value = _tenant.get()
    connection.execute(
        text("SELECT set_config('role', 'veritrack_app', true), "
             "set_config('app.org_id', :org, true), set_config('app.rls_bypass', :bypass, true)"),
        {"org": "" if value is None or value == SYSTEM else str(value), "bypass": "on" if value == SYSTEM else ""},
    )
