"""Celery tasks. Each task builds its own engine so asyncpg connections bind to the executing loop."""

import asyncio
import threading
import uuid

from app.worker import celery_app


def run_coro_blocking(coro):
    """Runs a coroutine on a dedicated thread with a fresh event loop."""
    outcome: dict = {}

    def _target():
        try:
            outcome["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE036 — propagated to caller below
            outcome["error"] = exc

    thread = threading.Thread(target=_target, name="celery-task-async", daemon=True)
    thread.start()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")


@celery_app.task(name="uploads.process_batch", bind=True, max_retries=1)
def process_batch_task(self, batch_id: str) -> dict:
    def _inner():
        from app.db.session import fresh_engine_and_factory
        from app.services.batch_service import run_batch_processing

        async def go():
            engine, factory = fresh_engine_and_factory()
            try:
                async with factory() as db:
                    return await run_batch_processing(db, batch_id)
            finally:
                await engine.dispose()

        return go()

    return run_coro_blocking(_inner())


@celery_app.task(name="analysis.run_analyze", bind=True, max_retries=1)
def run_analyze_task(self, batch_id: str, triggered_by: str | None = None, run_id: str | None = None) -> dict:
    def _inner():
        from app.db.session import fresh_engine_and_factory
        from app.services.analyze_service import execute_analysis

        async def go():
            engine, factory = fresh_engine_and_factory()
            try:
                async with factory() as db:
                    actor = uuid.UUID(triggered_by) if triggered_by else None
                    return await execute_analysis(db, batch_id, triggered_by=actor, run_id=run_id)
            finally:
                await engine.dispose()

        return go()

    return run_coro_blocking(_inner())
