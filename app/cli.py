"""Bootstrap CLI. The Master Admin is the only account seeded outside the API.

    python -m app.cli sync-master-admin       # create or update it from ADMIN_EMAIL / ADMIN_PASSWORD
    python -m app.cli create-master-admin [--email X --password Y] [--if-not-exists]
    python -m app.cli approve-domain <domain> [--creator-email X]
    python -m app.cli create-organization <name> --admin-email X   # a new tenant and its Master Admin

ADMIN_EMAIL administers the bootstrap organisation (the oldest one, created on first start). Every command
runs as a trusted internal step that can see all organisations (app/db/tenant.py) and names the organisation
of each row it writes.
"""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import hash_password, verify_password
from app.db.session import get_session_factory
from app.db.tenant import SYSTEM, tenant
from app.models.m365_domain import ApprovedM365Domain
from app.models.user import AuthType, User, UserRole
from app.services import audit_service, org_service


async def create_master_admin(
    email: str, password: str, if_not_exists: bool, org_id: uuid.UUID | None = None
) -> tuple[int, bool]:
    """Creates the Master Admin of org_id (default: the bootstrap organisation)."""
    factory = get_session_factory()
    with tenant(SYSTEM):
        async with factory() as db:
            return await _create_master_admin(db, email, password, if_not_exists, org_id)


async def _create_master_admin(db, email, password, if_not_exists, org_id) -> tuple[int, bool]:
    org_id = org_id or await org_service.bootstrap_org_id(db)
    existing_ma = (
        await db.execute(select(User).where(User.role == UserRole.MASTER_ADMIN, User.org_id == org_id))
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
        org_id=org_id,
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
    with tenant(SYSTEM):
        return await _sync_master_admin(email_norm, password, revoke_all_for_user)


async def _sync_master_admin(email_norm: str, password: str, revoke_all_for_user) -> str:
    async with get_session_factory()() as db:
        org_id = await org_service.bootstrap_org_id(db)
        admin = (
            await db.execute(select(User).where(User.role == UserRole.MASTER_ADMIN, User.org_id == org_id))
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
    """Approves the domain in the creator's organisation (the bootstrap one if the creator is unknown)."""
    domain_norm = domain.strip().lower().lstrip("@")
    factory = get_session_factory()
    with tenant(SYSTEM):
        async with factory() as db:
            return await _approve_domain(db, domain_norm, creator_email)


async def _approve_domain(db, domain_norm: str, creator_email: str) -> int:
    creator = (
        await db.execute(select(User).where(User.email == creator_email.lower()))
    ).scalar_one_or_none()
    org_id = creator.org_id if creator else await org_service.bootstrap_org_id(db)
    existing = (
        await db.execute(
            select(ApprovedM365Domain).where(ApprovedM365Domain.domain == domain_norm)
        )
    ).scalar_one_or_none()
    if existing is not None and existing.org_id != org_id:
        print(f"ERROR: {domain_norm} is approved by another organisation", file=sys.stderr)
        return 1
    if existing is not None:
        existing.is_active = True
    else:
        db.add(
            ApprovedM365Domain(
                org_id=org_id,
                domain=domain_norm,
                created_by=creator.id if creator else None,
            )
        )
    await db.commit()
    print(f"M365 domain approved: {domain_norm}")
    return 0


async def create_organization(name: str, admin_email: str) -> tuple[int, str | None]:
    """A new tenant and its Master Admin, with a generated password. Returns (exit code, password)."""
    from sqlalchemy.exc import IntegrityError

    from app.core.security import generate_initial_password

    password = generate_initial_password()
    with tenant(SYSTEM):
        async with get_session_factory()() as db:
            try:
                org = await org_service.create(db, name)
            except IntegrityError:
                print(f"ERROR: an organisation named {name.strip()!r} already exists", file=sys.stderr)
                return 1, None
            rc, created = await _create_master_admin(db, admin_email, password, False, org.id)
            if not created:
                await db.delete(org)
                await db.commit()
                return rc or 1, None
    print(f"Organisation created: {name.strip()} ({org.id})")
    return 0, password


def main() -> int:
    parser = argparse.ArgumentParser(prog="veritrack")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync-master-admin")
    sub.add_parser("sync-demo-account")

    p_admin = sub.add_parser("create-master-admin")
    p_admin.add_argument("--email", default=settings.admin_email)
    p_admin.add_argument("--password", default=settings.admin_password)
    p_admin.add_argument("--if-not-exists", action="store_true")

    p_domain = sub.add_parser("approve-domain")
    p_domain.add_argument("domain")
    p_domain.add_argument("--creator-email", default=settings.admin_email)

    p_org = sub.add_parser("create-organization")
    p_org.add_argument("name")
    p_org.add_argument("--admin-email", required=True)

    args = parser.parse_args()
    configure_logging()

    if args.command == "sync-master-admin":
        if not settings.admin_password:
            print("ADMIN_PASSWORD not set — Master Admin not synced", file=sys.stderr)
            return 0
        print(f"Master Admin {asyncio.run(sync_master_admin(settings.admin_email, settings.admin_password))}")
        return 0
    if args.command == "sync-demo-account":
        from app.services import demo_service

        async def _sync():
            with tenant(await demo_service.org_id()):
                async with get_session_factory()() as db:
                    return await demo_service.sync_account(db)

        user = asyncio.run(_sync())
        print("Demo account synced" if user else "DEMO_EMAIL / DEMO_PASSWORD not set — no demo account")
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
    if args.command == "create-organization":
        rc, org_password = asyncio.run(create_organization(args.name, args.admin_email))
        if org_password:
            print(f"Master Admin {args.admin_email.strip().lower()}, password (shown once): {org_password}")
        return rc
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
