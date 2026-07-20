from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress

from app.core.config import get_settings
from app.core.database import configure_database, database_ping, dispose_database
from app.core.redis import close_redis, redis_ping
from app.jobs.tasks import sync_running_knowledge_documents
from app.services.agent import redact_legacy_agent_snapshots

logger = logging.getLogger(__name__)


async def _wait_or_stop(stop: asyncio.Event, seconds: float) -> bool:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        return False
    return True


async def _fixed_delay_loop(
    stop: asyncio.Event,
    operation: Callable[[], Awaitable[int]],
    *,
    name: str,
    initial_delay: float,
    delay: float,
) -> None:
    if initial_delay and await _wait_or_stop(stop, initial_delay):
        return
    while not stop.is_set():
        started = time.monotonic()
        try:
            changed = await operation()
            logger.info(
                "Background job %s completed changed=%s duration_ms=%d",
                name,
                changed,
                (time.monotonic() - started) * 1000,
            )
        except Exception:
            logger.exception("Background job %s failed; the next fixed-delay pass will retry", name)
        if await _wait_or_stop(stop, delay):
            return


async def _finish_tasks(tasks: list[asyncio.Task[None]], timeout: float) -> bool:
    """Let active jobs finish, then cancel only those exceeding the shutdown budget."""

    _, pending = await asyncio.wait(tasks, timeout=max(timeout, 0.0))
    if not pending:
        return True
    logger.warning(
        "Graceful job shutdown timed out after %.1f seconds; cancelling %d task(s)",
        timeout,
        len(pending),
    )
    for task in pending:
        task.cancel()
    for task in pending:
        with suppress(asyncio.CancelledError):
            await task
    return False


async def run_worker(stop: asyncio.Event | None = None) -> None:
    settings = get_settings()
    os.environ["TZ"] = settings.timezone
    if hasattr(time, "tzset"):
        time.tzset()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    configure_database(settings)
    selected_stop = stop or asyncio.Event()

    if not settings.allow_start_without_dependencies:
        if not await database_ping():
            raise RuntimeError("database readiness check failed")
        if not await redis_ping():
            raise RuntimeError("Redis readiness check failed")

    # The retained Java service performs a blocking startup redaction pass,
    # then compensates rolling-deployment writes after 5 seconds and every
    # 15 seconds.  The standalone worker preserves those timings while the
    # Redis lock makes multiple worker replicas safe.
    await redact_legacy_agent_snapshots()
    tasks = [
        asyncio.create_task(
            _fixed_delay_loop(
                selected_stop,
                redact_legacy_agent_snapshots,
                name="agent-snapshot-redaction",
                initial_delay=5,
                delay=15,
            )
        ),
        asyncio.create_task(
            _fixed_delay_loop(
                selected_stop,
                sync_running_knowledge_documents,
                name="knowledge-document-status",
                initial_delay=0,
                delay=30,
            )
        ),
    ]
    try:
        await selected_stop.wait()
    finally:
        await _finish_tasks(tasks, settings.graceful_shutdown_seconds)
        await close_redis()
        await dispose_database()


def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stop.set)
    try:
        loop.run_until_complete(run_worker(stop))
    finally:
        loop.close()


if __name__ == "__main__":
    main()
