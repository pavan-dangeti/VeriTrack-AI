"""Leases on processing jobs (migration 0010).

A claim gives the worker a fresh token and an expiry. While it works, `kept` pushes the expiry back every
quarter of the lease from a session of its own. Every write the worker makes is conditional on still holding
the token, so:

- a worker that dies stops renewing; once the lease runs out another worker may claim the job, and the
  reaper (app/services/jobs.py) makes sure one does;
- a worker that froze (a long pause, a suspended VM) and wakes up after someone else took over finds its
  token gone, and its late writes change nothing.

So a job can be started more than once, but its result is written exactly once.
"""

import asyncio
import os
import socket
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from sqlalchemy import func, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("leases")

# who holds a lease, for logs; the token itself is per claim
WORKER = f"{socket.gethostname()}:{os.getpid()}"


def length() -> timedelta:
    return timedelta(seconds=settings.job_lease_seconds)


def new_expiry():
    return func.now() + length()


def lapsed(model):
    """In progress, but nobody holds a live lease on it: its worker died (or predates leases)."""
    return (model.status == "PROCESSING") & or_(model.lease_expires_at.is_(None),
                                                 model.lease_expires_at < func.now())


@asynccontextmanager
async def kept(db: AsyncSession, model, row_id: uuid.UUID, token: uuid.UUID) -> AsyncIterator[asyncio.Event]:
    """Renews the lease while the block runs. The event is set once the lease is found taken over; the
    block's own writes are fenced either way, so this only lets it stop early."""
    stop, lost = asyncio.Event(), asyncio.Event()

    async def renew() -> None:
        async with AsyncSession(db.bind) as session:
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), settings.job_lease_seconds / 4)
                    return
                except TimeoutError:
                    pass
                try:
                    held = (await session.execute(
                        update(model).where(model.id == row_id, model.lease_token == token)
                        .values(lease_expires_at=new_expiry()).returning(model.id)
                    )).scalar_one_or_none()
                    await session.commit()
                except Exception as exc:  # noqa: BLE001 — a missed renewal is retried next beat
                    await session.rollback()
                    log.warning("lease_renewal_failed", job=model.__tablename__, id=str(row_id),
                                error=str(exc)[:200])
                    continue
                if held is None:
                    log.warning("lease_lost", job=model.__tablename__, id=str(row_id), worker=WORKER)
                    lost.set()
                    return

    task = asyncio.create_task(renew())
    try:
        yield lost
    finally:
        stop.set()
        await task
