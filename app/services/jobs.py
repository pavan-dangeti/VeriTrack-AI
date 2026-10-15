"""Job dispatch for batch processing and analysis.

PROCESSING_MODE picks where work runs. Batches left QUEUED/PROCESSING by a restart are resumed on
startup; the atomic claims in batch_service make that safe across replicas.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.logging import get_logger
from app.db.tenant import SYSTEM, tenant

log = get_logger("jobs")

_running: set[asyncio.Task] = set()


async def batch_org(factory, batch_id: str):
    """A job runs in the organisation of its batch. The request that queued it may be gone (a Celery worker,
    or recovery after a restart), so the organisation is looked up rather than inherited."""
    import uuid

    from app.models.uploads import UploadBatch

    with tenant(SYSTEM):
        async with factory() as db:
            return (await db.execute(
                select(UploadBatch.org_id).where(UploadBatch.id == uuid.UUID(batch_id))
            )).scalar_one_or_none()


def _spawn(coro, name: str) -> None:
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _running.add(task)
    task.add_done_callback(_running.discard)


async def _process_batch_job(batch_id: str) -> dict:
    from app.db.session import get_session_factory
    from app.services.batch_service import run_batch_processing

    with tenant(await batch_org(get_session_factory(), batch_id)):
        try:
            async with get_session_factory()() as db:
                return await run_batch_processing(db, batch_id)
        except Exception as exc:  # noqa: BLE001 — a job must never kill the loop
            log.error("batch_job_failed", batch_id=batch_id, exc_info=exc)
            await _mark_batch_failed(batch_id, exc)
            return {"status": "error"}


async def _mark_batch_failed(batch_id: str, exc: Exception) -> None:
    import uuid

    from app.db.session import get_session_factory
    from app.models.uploads import BatchStatus, UploadBatch

    async with get_session_factory()() as db:
        await db.execute(
            update(UploadBatch)
            .where(UploadBatch.id == uuid.UUID(batch_id))
            .values(status=BatchStatus.FAILED, completed_at=datetime.now(UTC))
        )
        await db.commit()


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
    from app.db.session import get_session_factory
    from app.services.analyze_service import execute_analysis

    with tenant(await batch_org(get_session_factory(), batch_id)):
        async with get_session_factory()() as db:
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


async def recover_interrupted_batches(stale_after: timedelta = timedelta(minutes=10)) -> int:
    if settings.processing_mode != "background":
        return 0
    from app.db.session import get_session_factory

    cutoff = datetime.now(UTC) - stale_after
    with tenant(SYSTEM):  # every organisation's batches
        stuck = await _requeue_stuck_batches(get_session_factory(), cutoff)
    for bid in stuck:
        _spawn(_process_batch_job(str(bid)), f"batch:{bid}")
    if stuck:
        log.info("recovered_batches", count=len(stuck))
    return len(stuck)


async def _requeue_stuck_batches(factory, cutoff) -> list:
    from app.models.uploads import BatchStatus, FileStatus, UploadBatch, UploadedFile

    async with factory() as db:
        stuck = (
            await db.execute(
                select(UploadBatch.id).where(
                    (UploadBatch.status == BatchStatus.QUEUED)
                    | ((UploadBatch.status == BatchStatus.PROCESSING)
                       & (UploadBatch.created_at < cutoff))
                )
            )
        ).scalars().all()
        if not stuck:
            return []
        await db.execute(
            update(UploadedFile)
            .where(UploadedFile.batch_id.in_(stuck), UploadedFile.status == FileStatus.PROCESSING)
            .values(status=FileStatus.QUEUED)
        )
        await db.execute(
            update(UploadBatch).where(UploadBatch.id.in_(stuck)).values(status=BatchStatus.QUEUED)
        )
        await db.commit()
    return list(stuck)


async def recover_interrupted_analyses(stale_after: timedelta = timedelta(minutes=10)) -> int:
    """Re-runs analyses a previous process left RUNNING (partial results are
    cleared by execute_analysis before it starts again)."""
    if settings.processing_mode != "background":
        return 0
    from app.db.session import get_session_factory
    from app.models.analysis import AnalysisRun, AnalysisStatus

    cutoff = datetime.now(UTC) - stale_after
    with tenant(SYSTEM):  # every organisation's runs
        async with get_session_factory()() as db:
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
