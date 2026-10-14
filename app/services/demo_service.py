"""Public demo account: a Manager with synthetic data only, reset daily by the API itself.

Enabled by DEMO_EMAIL / DEMO_PASSWORD. The account cannot create users, its analyses never send real
email, and every DEMO_RESET_HOURS its data is replaced with the same synthetic employees, leave register
and four sample timesheets (app/demo/), already processed and analysed.
"""

import asyncio
import uuid
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.db.tenant import SYSTEM, tenant
from app.models.analysis import AnalysisRun, GeneratedReport
from app.models.audit_log import AuditLog
from app.models.employees import Employee
from app.models.leaves import CompanyLeave
from app.models.uploads import BatchKind, UploadBatch, UploadedFile
from app.models.user import AuthType, User, UserRole
from app.services import audit_service, org_service

log = get_logger("demo")

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "demo"
SAMPLE_SHEETS = ("timesheet_000.png", "timesheet_004.png", "timesheet_007.png", "timesheet_013.png")
REPOSITORY_CSV = (
    "Employee ID,Full Name,Company Email,Personal Email,Department\n"
    "103729,Golf Anonymous,golf.anonymous@example.com,,Engineering\n"
    "158082,Kilo Specimen,kilo.specimen@example.com,,Engineering\n"
    "141220,Bravo Example,,bravo.example@example.net,Design\n"
    "197061,Echo Specimen,echo.specimen@example.com,,Design\n"
)
# two timesheet leave days are deliberately missing here (141220 on 28 Jul 2025, 197061 on 18 Jun 2025)
LEAVE_CSV = (
    "Employee ID,From Date,To Date,Leave Type\n"
    "103729,09-03-2026,,Casual\n103729,2026-03-24,,Casual\n"
    "141220,01/07/2025,01/07/2025,Sick\n141220,03-Jul-2025,,Casual\n141220,2025-07-14,,Casual\n"
    "197061,02-Jun-2025,03-Jun-2025,Earned\n197061,11/06/2025,,Casual\n"
)
_LOCK_ID = zlib.crc32(b"veritrack-demo-reset")


def enabled() -> bool:
    return bool(settings.demo_email and settings.demo_password)


async def org_id() -> uuid.UUID:
    """The demo account lives in the bootstrap organisation; its functions below run with that tenant set."""
    from app.db.session import get_session_factory

    with tenant(SYSTEM):
        async with get_session_factory()() as db:
            return await org_service.bootstrap_org_id(db)


def is_demo(user: User | None) -> bool:
    return enabled() and user is not None and user.email == (settings.demo_email or "").strip().lower()


async def _created_as_demo(db: AsyncSession, user: User) -> bool:
    return (await db.execute(select(AuditLog.id).where(
        AuditLog.action == audit_service.ACTION_DEMO_ACCOUNT_CREATED, AuditLog.target_id == str(user.id)
    ).limit(1))).first() is not None


async def sync_account(db: AsyncSession) -> User | None:
    """Creates the demo Manager, or brings its password in line with DEMO_PASSWORD.

    Only an account this service created is ever adopted: pointing DEMO_EMAIL at a real user must not
    hand that user's login to the public and wipe their data on the next reset."""
    if not enabled():
        return None
    email = (settings.demo_email or "").strip().lower()
    password = settings.demo_password or ""
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is not None and not await _created_as_demo(db, user):
        raise SystemExit(f"ERROR: DEMO_EMAIL {email} belongs to an existing account that is not the demo account")
    if user is None:
        admin = (await db.execute(select(User).where(User.role == UserRole.MASTER_ADMIN))).scalar_one_or_none()
        if admin is None:
            raise SystemExit("ERROR: the demo account needs a Master Admin (set ADMIN_EMAIL / ADMIN_PASSWORD)")
        user = User(email=email, full_name="Demo Manager", role=UserRole.MANAGER, auth_type=AuthType.PASSWORD,
                    password_hash=await asyncio.to_thread(hash_password, password), created_by=admin.id)
        db.add(user)
        await db.commit()
        await audit_service.record(db, action=audit_service.ACTION_DEMO_ACCOUNT_CREATED,
                                   result=audit_service.AuditResult.SUCCESS, actor_user_id=admin.id,
                                   target_entity="user", target_id=str(user.id))
    elif not user.password_hash or not await asyncio.to_thread(verify_password, password, user.password_hash):
        user.password_hash = await asyncio.to_thread(hash_password, password)
        await db.commit()
    return user


async def reset(db: AsyncSession, demo: User, *, sheets: tuple[str, ...] = SAMPLE_SHEETS) -> dict:
    """Replaces all of the demo Manager's data with the synthetic sample set."""
    from app.services.analyze_service import claim_analysis, execute_analysis
    from app.services.batch_service import create_batch, run_batch_processing
    from app.services.storage import get_storage

    keys = list((await db.execute(
        select(UploadedFile.storage_key).where(UploadedFile.manager_id == demo.id))).scalars())
    keys += list((await db.execute(
        select(GeneratedReport.storage_key).join(AnalysisRun, AnalysisRun.id == GeneratedReport.run_id)
        .where(AnalysisRun.manager_id == demo.id))).scalars())
    # batches cascade to files, extracted rows, analysis runs, violations and reports
    await db.execute(delete(UploadBatch).where(UploadBatch.manager_id == demo.id))
    await db.execute(delete(Employee).where(Employee.manager_id == demo.id))
    await db.execute(delete(CompanyLeave).where(CompanyLeave.manager_id == demo.id))
    await db.commit()
    storage = get_storage()
    for key in keys:
        await asyncio.to_thread(storage.delete, key)

    for kind, name, body in ((BatchKind.EMPLOYEE_REPO, "repository.csv", REPOSITORY_CSV.encode()),
                             (BatchKind.COMPANY_LEAVE, "leave-register.csv", LEAVE_CSV.encode())):
        batch = await create_batch(db, manager=demo, kind=kind, files=[(name, body)])
        await run_batch_processing(db, str(batch.id))
    violations = 0
    if sheets:
        files = [(n, (SAMPLES_DIR / n).read_bytes()) for n in sheets]
        batch = await create_batch(db, manager=demo, kind=BatchKind.TIMESHEET, files=files)
        await run_batch_processing(db, str(batch.id))
        processed = await db.get(UploadBatch, batch.id, populate_existing=True)
        if processed is not None and processed.processed_files:
            run = await claim_analysis(db, processed, demo.id)
            result = await execute_analysis(db, str(processed.id), triggered_by=demo.id, run_id=str(run.id))
            violations = int(result.get("violations", 0))
    await audit_service.record(db, action=audit_service.ACTION_DEMO_RESET, result=audit_service.AuditResult.SUCCESS,
                               actor_user_id=demo.id, target_entity="user", target_id=str(demo.id),
                               metadata={"files_removed": len(keys), "violations": violations})
    log.info("demo_reset", files_removed=len(keys), violations=violations)
    return {"files_removed": len(keys), "violations": violations}


async def reset_if_due(db: AsyncSession) -> bool:
    """Resets when the last reset is older than DEMO_RESET_HOURS. A session-level advisory lock keeps two
    API instances from resetting at the same time."""
    if not enabled():
        return False
    if not (await db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_ID})).scalar_one():
        return False
    try:
        last = (await db.execute(
            select(func.max(AuditLog.timestamp)).where(AuditLog.action == audit_service.ACTION_DEMO_RESET)
        )).scalar_one_or_none()
        if last is not None and datetime.now(UTC) - last < timedelta(hours=settings.demo_reset_hours):
            return False
        demo = await sync_account(db)
        if demo is None:
            return False
        await reset(db, demo)
        return True
    finally:
        await db.rollback()   # a failed reset leaves the transaction aborted; unlock must still run
        await db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_ID})
        await db.commit()


async def run_scheduler(check_every: timedelta = timedelta(hours=1)) -> None:
    from app.db.session import get_session_factory

    while True:
        try:
            with tenant(await org_id()):
                async with get_session_factory()() as db:
                    await reset_if_due(db)
        except (Exception, SystemExit) as exc:  # noqa: BLE001 — a failed reset (or bad DEMO_EMAIL) must not stop the API
            log.warning("demo_reset_failed", error=str(exc)[:200])
        await asyncio.sleep(check_every.total_seconds())


def sample_path(name: str) -> Path | None:
    return SAMPLES_DIR / name if name in SAMPLE_SHEETS else None
