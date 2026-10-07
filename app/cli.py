"""Bootstrap CLI. The Master Admin is the only account seeded outside the API.

    python -m app.cli sync-master-admin       # create or update it from ADMIN_EMAIL / ADMIN_PASSWORD
    python -m app.cli create-master-admin [--email X --password Y] [--if-not-exists]
    python -m app.cli approve-domain <domain> [--creator-email X]
"""

import argparse
import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import hash_password, verify_password
from app.db.session import get_session_factory
from app.models.m365_domain import ApprovedM365Domain
from app.models.user import AuthType, User, UserRole
from app.services import audit_service


async def create_master_admin(
    email: str, password: str, if_not_exists: bool
) -> tuple[int, bool]:
    factory = get_session_factory()
    async with factory() as db:
        existing_ma = (
            await db.execute(select(User).where(User.role == UserRole.MASTER_ADMIN))
        ).scalar_one_or_none()
        if existing_ma is not None:
            if if_not_exists:
                print(f"Master Admin already exists: {existing_ma.email}")
                return 0, False
            print("ERROR: a Master Admin already exists", file=sys.stderr)
            return 1, False

        email_norm = email.strip().lower()
        dup = await db.execute(
            select(User).where(User.email == email_norm)
        )
        if dup.scalar_one_or_none() is not None:
            print(f"ERROR: email already in use by another account: {email_norm}",
                  file=sys.stderr)
            return 1, False

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
        return 0, True


async def sync_master_admin(email: str, password: str) -> str:
    """Makes the Master Admin match the configured credentials, so rotating ADMIN_PASSWORD (or changing
    ADMIN_EMAIL) in the host's environment takes effect on the next start. Any change signs the admin out
    everywhere. Returns "created", "updated" or "unchanged"."""
    from app.services.auth_service import revoke_all_for_user

    email_norm = email.strip().lower()
    async with get_session_factory()() as db:
        admin = (
            await db.execute(select(User).where(User.role == UserRole.MASTER_ADMIN))
        ).scalar_one_or_none()
    if admin is None:
        rc, _ = await create_master_admin(email_norm, password, if_not_exists=False)
        if rc:
            raise SystemExit(rc)
        return "created"

    async with get_session_factory()() as db:
        admin = await db.get(User, admin.id)
        assert admin is not None
        changed = []
        if admin.email != email_norm:
            taken = (await db.execute(select(User.id).where(User.email == email_norm))).first()
            if taken:
                raise SystemExit(f"ERROR: {email_norm} already belongs to another account")
            admin.email = email_norm
            changed.append("email")
        if not admin.password_hash or not verify_password(password, admin.password_hash):
            admin.password_hash = hash_password(password)
            admin.failed_login_attempts = 0
            admin.locked_until = None
            changed.append("password")
        if not changed:
            return "unchanged"
        await db.commit()
        await revoke_all_for_user(db, admin.id)
        await audit_service.record(
            db,
            action=audit_service.ACTION_ADMIN_CREDENTIALS_SYNCED,
            result=audit_service.AuditResult.SUCCESS,
            actor_user_id=admin.id,
            target_entity="user",
            target_id=str(admin.id),
            metadata={"changed": changed},
        )
        return "updated"


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

    sub.add_parser("sync-master-admin")

    p_admin = sub.add_parser("create-master-admin")
    p_admin.add_argument("--email", default=settings.admin_email)
    p_admin.add_argument("--password", default=settings.admin_password)
    p_admin.add_argument("--if-not-exists", action="store_true")

    p_domain = sub.add_parser("approve-domain")
    p_domain.add_argument("domain")
    p_domain.add_argument("--creator-email", default=settings.admin_email)

    args = parser.parse_args()
    configure_logging()

    if args.command == "sync-master-admin":
        if not settings.admin_password:
            print("ADMIN_PASSWORD not set — Master Admin not synced", file=sys.stderr)
            return 0
        print(f"Master Admin {asyncio.run(sync_master_admin(settings.admin_email, settings.admin_password))}")
        return 0
    if args.command == "create-master-admin":
        generated = args.password is None
        if generated:
            # No --password flag and no ADMIN_PASSWORD env: generate a
            # strong random password and print it once (never stored/logged).
            from app.core.security import generate_initial_password

            password = generate_initial_password()
        else:
            password = args.password
        rc, created = asyncio.run(
            create_master_admin(args.email, password, args.if_not_exists)
        )
        if generated and created:
            print(f"Generated Master Admin password (shown once): {password}")
        return rc
    if args.command == "approve-domain":
        return asyncio.run(approve_domain(args.domain, args.creator_email))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
