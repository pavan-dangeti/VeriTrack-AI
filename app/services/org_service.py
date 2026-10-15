"""Organisations. The bootstrap organisation is the one ADMIN_EMAIL administers (and the demo account lives
in); further organisations are created by the platform operator with `python -m app.cli create-organization`.
Both functions need the SYSTEM tenant (app/db/tenant.py).
"""

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization

DEFAULT_NAME = "Default organisation"


async def bootstrap_org_id(db: AsyncSession) -> uuid.UUID:
    """The oldest organisation, created on first start. Safe when two instances start at once: the unique name
    index turns the second insert into a no-op."""
    await db.execute(text("""
        INSERT INTO organizations (name) SELECT :name WHERE NOT EXISTS (SELECT 1 FROM organizations)
        ON CONFLICT ((lower(name))) DO NOTHING
    """), {"name": DEFAULT_NAME})
    org_id = (await db.execute(
        select(Organization.id).order_by(Organization.created_at, Organization.id).limit(1)
    )).scalar_one()
    await db.commit()
    return org_id


async def create(db: AsyncSession, name: str) -> Organization:
    org = Organization(name=name.strip())
    db.add(org)
    await db.commit()
    return org
