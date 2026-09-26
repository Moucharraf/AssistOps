import asyncio
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress

import psycopg
import structlog
from pydantic import ValidationError

from assistops.business import ToolsProcessor
from assistops.config import Settings
from assistops.events import EventInput
from assistops.jobs import Exhausted, JobStore
from assistops.observability import configure_logging
from assistops.rag_agent import RagProcessor
from assistops.supervisor import SupervisorProcessor
from assistops.ticket_delivery import deliver_once
from assistops.tracing import correlation_ref, record, span, tracing_session

logger = structlog.get_logger()
Processor = Callable[[EventInput], Awaitable[dict]]


async def demo_processor(event: EventInput) -> dict:
    """Exercise infrastructure without claiming to answer the business request."""
    return {
        "processor": "demo",
        "outcome": "acknowledged",
        "business_action_executed": False,
        "message": "Démonstration terminée. Les agents métier restent à brancher.",
    }


async def run_once(store: JobStore, processor: Processor) -> bool:
    lease = await asyncio.to_thread(store.claim)
    if lease is None:
        return False
    if isinstance(lease, Exhausted):
        logger.warning("job_attempts_exhausted", event_id=str(lease.event_id))
        return True
    with span(
        "worker",
        event_id=str(lease.event_id),
        correlation_ref=correlation_ref(lease.correlation_id),
        attempt=lease.attempt,
    ):
        return await process_lease(store, processor, lease)


async def process_lease(store, processor, lease):
    context = structlog.contextvars.bind_contextvars(
        correlation_id=lease.correlation_id, event_id=str(lease.event_id), attempt=lease.attempt
    )
    try:
        result = None
        error = None
        try:
            event = EventInput.model_validate(lease.payload)
        except ValidationError:
            error = "invalid_event"
        else:
            try:
                async with asyncio.timeout(store.settings.worker_timeout_seconds):
                    handler = ToolsProcessor(store.settings) if event.tool_call else processor
                    result = await handler(event)
                if not isinstance(result, dict):
                    raise TypeError("Processor must return a dictionary")
            except TimeoutError:
                error = "processor_timeout"
            except Exception as exc:
                error = "processor_error"
                logger.warning("processor_failed", error_type=type(exc).__name__)
        saved = await asyncio.to_thread(
            store.finish, lease, result=result if error is None else None, error=error
        )
        record(
            {**(result or {}), "job_saved": saved, **({"outcome": "unavailable"} if error else {})}
        )
        logger.info("job_outcome_saved" if saved else "job_lease_lost", error_code=error)
    finally:
        structlog.contextvars.reset_contextvars(**context)
    return True


async def serve(settings: Settings, stop: asyncio.Event) -> None:
    with tracing_session(settings):
        await serve_with_tracing(settings, stop)


async def serve_with_tracing(settings: Settings, stop: asyncio.Event) -> None:
    if settings.worker_processor == "disabled":
        raise ValueError("Worker processor is disabled")
    if settings.worker_processor == "supervisor":
        processor = SupervisorProcessor(settings)
    else:
        processor = RagProcessor(settings) if settings.worker_processor == "rag" else demo_processor
    store = JobStore(settings)
    while not stop.is_set():
        try:
            did_work = await run_once(store, processor)
            delivered = await asyncio.to_thread(deliver_once, settings)
            did_work = did_work or delivered
        except psycopg.Error as exc:
            # An uncertain commit is reconciled by the lease and durable job state.
            logger.warning("worker_storage_unavailable", error_type=type(exc).__name__)
            did_work = False
        if not did_work and not stop.is_set():
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)


async def main(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    logger.info("worker_started", processor=settings.worker_processor)
    await serve(settings, stop)
    logger.info("worker_stopped")


if __name__ == "__main__":
    configure_logging()
    settings = Settings()
    if settings.worker_processor == "disabled":
        logger.error("worker_processor_disabled")
        raise SystemExit(1)
    asyncio.run(main(settings))
