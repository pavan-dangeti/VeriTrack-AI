"""Celery tasks.

Workers are sync processes; business logic is async. Each task builds its
own engine (see db.session.fresh_engine_and_factory) so asyncpg connections
are always bound to the executing loop — required both under real workers
and Celery eager mode, where the "worker" shares the API's thread.
"""

import asyncio
import threading

from app.worker import celery_app


def run_coro_blocking(coro):
    """Runs a coroutine on a dedicated thread + fresh loop.

    Real workers have no running loop here, and Celery-eager calls happen
    inside the API's live loop where starting one is forbidden — a private
    thread works identically for both.
    """
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
def run_analyze_task(self, batch_id: str) -> dict:
    def _inner():
        from app.db.session import fresh_engine_and_factory
        from app.services.analyze_service import execute_analysis

        async def go():
            engine, factory = fresh_engine_and_factory()
            try:
                async with factory() as db:
                    return await execute_analysis(db, batch_id)
            finally:
                await engine.dispose()

        return go()

    return run_coro_blocking(_inner())
