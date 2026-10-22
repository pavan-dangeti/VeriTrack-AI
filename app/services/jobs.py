"""Job dispatch for batch processing and analysis.

PROCESSING_MODE picks where work runs. A reaper runs at startup and then every half lease: it re-dispatches
jobs whose worker is gone (app/services/leases.py), so a killed worker's batch is finished by another. Leases
make duplicate dispatches harmless, which is what lets every replica run the reaper.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.tenant import SYSTEM, tenant

log = get_logger("jobs")

_running: set[asyncio.Task] = set()


async def batch_org(factory, batch_id: str):
    """A job runs in the organisation of its batch. The request that queued it may be gone (a Celery worker,
    or the reaper), so the organisation is looked up rather than inherited."""
    from app.models.uploads import UploadBatch

    return await _org_of(factory, UploadBatch, batch_id)


async def _org_of(factory, model, row_id: str):
    import uuid

    with tenant(SYSTEM):
        async with factory() as db:
            return (await db.execute(
                select(model.org_id).where(model.id == uuid.UUID(str(row_id)))
            )).scalar_one_or_none()


def _spawn(coro, name: str) -> None:
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _process_batch_job(batch_id: str) -> dict:
    from app.db.session import get_job_session_factory
    from app.services.batch_service import run_batch_processing

    try:
        with tenant(await batch_org(get_job_session_factory(), batch_id)):
            async with get_job_session_factory()() as db:
                return await run_batch_processing(db, batch_id)
    except Exception as exc:  # noqa: BLE001 — a job must never kill the loop; the reaper retries it
        log.error("batch_job_failed", batch_id=batch_id, exc_info=exc)
        return {"status": "error"}


async def _process_file_job(file_id) -> None:
    from app.db.session import get_job_session_factory
    from app.models.uploads import UploadedFile
    from app.services.extraction.pipeline import process_uploaded_file

    try:
        with tenant(await _org_of(get_job_session_factory(), UploadedFile, file_id)):
            async with get_job_session_factory()() as db:
                await process_uploaded_file(db, file_id)
    except Exception as exc:  # noqa: BLE001
        log.error("file_job_failed", file_id=str(file_id), exc_info=exc)


async def dispatch_batch(batch_id: str) -> None:
    mode = settings.processing_mode
    if mode == "celery":
        from app.worker_tasks import process_batch_task

        process_batch_task.delay(batch_id)
    elif mode == "inline":
        await _process_batch_job(batch_id)
    else:
        _spawn(_process_batch_job(batch_id), f"batch:{batch_id}")


async def _analysis_job(batch_id: str, triggered_by, run_id: str | None = None) -> dict:
    from app.db.session import get_job_session_factory
    from app.services.analyze_service import execute_analysis

    with tenant(await batch_org(get_job_session_factory(), batch_id)):
        async with get_job_session_factory()() as db:
            return await execute_analysis(db, batch_id, triggered_by=triggered_by, run_id=run_id)


async def dispatch_analysis(batch_id: str, triggered_by, run_id: str | None = None) -> dict | None:
    """Inline mode returns the result; queued modes return None (poll the
    analysis endpoint for status)."""
    mode = settings.processing_mode
    if mode == "celery":
        from app.worker_tasks import run_analyze_task

        run_analyze_task.delay(batch_id, str(triggered_by) if triggered_by else None, run_id)
        return None
    if mode == "inline":
        return await _analysis_job(batch_id, triggered_by, run_id)

    async def guarded():
        try:
            await _analysis_job(batch_id, triggered_by, run_id)
        except Exception as exc:  # noqa: BLE001 — recorded on the run row
            log.warning("analysis_job_failed", batch_id=batch_id, error=str(exc)[:200])

    _spawn(guarded(), f"analysis:{batch_id}")
    return None


async def reap() -> dict:
    """Re-dispatches every job whose worker is gone: batches whose lease ran out, batches queued for longer
    than a lease (their dispatch was lost), and files whose lease ran out outside a running batch (an
    interrupted reprocess request). Returns how many of each."""
    from app.db.session import get_job_session_factory
    from app.models.uploads import BatchStatus, UploadBatch, UploadedFile
    from app.services import leases

    with tenant(SYSTEM):  # every organisation's jobs
        async with get_job_session_factory()() as db:
            batches = list((await db.execute(select(UploadBatch.id).where(or_(
                leases.lapsed(UploadBatch),
                (UploadBatch.status == BatchStatus.QUEUED) & (UploadBatch.created_at < func.now() - leases.length()),
            )))).scalars())
            files = list((await db.execute(
                select(UploadedFile.id).join(UploadBatch, UploadBatch.id == UploadedFile.batch_id)
                .where(leases.lapsed(UploadedFile), UploadBatch.status != BatchStatus.PROCESSING)
            )).scalars())
    for bid in batches:
        await dispatch_batch(str(bid))
    for fid in files:
        _spawn(_process_file_job(fid), f"file:{fid}")
    if batches or files:
        log.info("reaped", batches=len(batches), files=len(files))
    return {"batches": len(batches), "files": len(files)}


async def run_reaper() -> None:
    while True:
        try:
            await reap()
        except Exception as exc:  # noqa: BLE001 — the database may be migrating or briefly away
            log.warning("reaper_failed", error=str(exc)[:200])
        await asyncio.sleep(settings.job_lease_seconds / 2)


async def recover_interrupted_analyses(stale_after: timedelta = timedelta(minutes=10)) -> int:
    """Re-runs analyses a previous process left RUNNING (partial results are
    cleared by execute_analysis before it starts again)."""
    if settings.processing_mode != "background":
        return 0
    from app.db.session import get_job_session_factory
    from app.models.analysis import AnalysisRun, AnalysisStatus

    cutoff = datetime.now(UTC) - stale_after
    with tenant(SYSTEM):  # every organisation's runs
        async with get_job_session_factory()() as db:
            stuck = (await db.execute(
                select(AnalysisRun.id, AnalysisRun.batch_id, AnalysisRun.triggered_by).where(
                    AnalysisRun.status == AnalysisStatus.RUNNING, AnalysisRun.started_at < cutoff
                )
            )).all()
    for run_id, batch_id, by in stuck:
        _spawn(_analysis_job(str(batch_id), by, str(run_id)), f"analysis:{batch_id}")
    if stuck:
        log.info("recovered_analyses", count=len(stuck))
    return len(stuck)


async def drain(timeout: float = 30.0) -> None:
    """Lets in-flight jobs finish on shutdown (bounded)."""
    if _running:
        await asyncio.wait(set(_running), timeout=timeout)
