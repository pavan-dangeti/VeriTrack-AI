"""Bootstrap CLI.

Usage:
    python -m app.cli create-master-admin [--email X --password Y] [--if-not-exists]
    python -m app.cli approve-domain <domain> [--creator-email X]

The Master Admin is the only account seeded this way; all other accounts are
created through the API by authorized roles.
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.db.session import get_session_factory
from app.models.m365_domain import ApprovedM365Domain
from app.models.user import AuthType, User, UserRole
from app.services import audit_service


async def create_master_admin(email: str, password: str, if_not_exists: bool) -> int:
    factory = get_session_factory()
    async with factory() as db:
        existing_ma = (
            await db.execute(select(User).where(User.role == UserRole.MASTER_ADMIN))
        ).scalar_one_or_none()
        if existing_ma is not None:
            if if_not_exists:
                print(f"Master Admin already exists: {existing_ma.email}")
                return 0
            print("ERROR: a Master Admin already exists", file=sys.stderr)
            return 1

        email_norm = email.strip().lower()
        dup = await db.execute(
            select(User).where(User.email == email_norm)
        )
        if dup.scalar_one_or_none() is not None:
            print(f"ERROR: email already in use by another account: {email_norm}",
                  file=sys.stderr)
            return 1

        admin = User(
            email=email_norm,
            role=UserRole.MASTER_ADMIN,
            auth_type=AuthType.PASSWORD,
            password_hash=hash_password(password),
            created_by=None,  # trigger requires NULL for MASTER_ADMIN bootstrap
        )
        db.add(admin)
        await db.commit()
        await audit_service.record(
            db,
            action=audit_service.ACTION_BOOTSTRAP_ADMIN,
            result=audit_service.AuditResult.SUCCESS,
            actor_user_id=admin.id,
            target_entity="user",
            target_id=str(admin.id),
        )
        print(f"Master Admin created: {email_norm}")
        return 0


async def approve_domain(domain: str, creator_email: str) -> int:
    domain_norm = domain.strip().lower().lstrip("@")
    factory = get_session_factory()
    async with factory() as db:
        creator = (
            await db.execute(select(User).where(User.email == creator_email.lower()))
        ).scalar_one_or_none()
        existing = (
            await db.execute(
                select(ApprovedM365Domain).where(ApprovedM365Domain.domain == domain_norm)
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.is_active = True
        else:
            db.add(
                ApprovedM365Domain(
                    domain=domain_norm,
                    created_by=creator.id if creator else None,
                )
            )
        await db.commit()
        print(f"M365 domain approved: {domain_norm}")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="veritrack")
    sub = parser.add_subparsers(dest="command", required=True)

    p_admin = sub.add_parser("create-master-admin")
    p_admin.add_argument("--email", default=settings.seed_admin_email)
    p_admin.add_argument("--password", default=settings.seed_admin_password)
    p_admin.add_argument("--if-not-exists", action="store_true")

    p_domain = sub.add_parser("approve-domain")
    p_domain.add_argument("domain")
    p_domain.add_argument("--creator-email", default=settings.seed_admin_email)

    args = parser.parse_args()
    configure_logging()

    if args.command == "create-master-admin":
        return asyncio.run(
            create_master_admin(args.email, args.password, args.if_not_exists)
        )
    if args.command == "approve-domain":
        return asyncio.run(approve_domain(args.domain, args.creator_email))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
