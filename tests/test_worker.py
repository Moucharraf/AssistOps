import asyncio
from unittest.mock import Mock
from uuid import uuid4

import psycopg
import pytest
from pydantic import ValidationError
from test_events import PAYLOAD

from assistops.config import Settings
from assistops.jobs import Lease
from assistops.worker import demo_processor, run_once, serve


def store_for(settings):
    settings.worker_processor = "demo"
    store = Mock(settings=settings)
    store.claim.return_value = Lease(uuid4(), uuid4(), 1, PAYLOAD, "worker-test")
    store.finish.return_value = True
    return store


def test_processor_timeout_retries(settings):
    settings.worker_timeout_seconds = 0.01
    store = store_for(settings)

    async def stuck(_event):
        await asyncio.sleep(30)

    assert asyncio.run(run_once(store, stuck)) is True
    assert store.finish.call_args.kwargs == {"result": None, "error": "processor_timeout"}


def test_exception_message_never_logged(settings, capsys):
    store = store_for(settings)

    async def broken(_event):
        raise RuntimeError("sensitive-provider-secret")

    asyncio.run(run_once(store, broken))
    assert store.finish.call_args.kwargs["error"] == "processor_error"
    assert "sensitive-provider-secret" not in capsys.readouterr().out


def test_invalid_persisted_event_fails_without_calling_processor(settings):
    store = store_for(settings)
    store.claim.return_value = Lease(uuid4(), uuid4(), 1, {}, "invalid-test")
    processor = Mock()
    asyncio.run(run_once(store, processor))
    processor.assert_not_called()
    assert store.finish.call_args.kwargs["error"] == "invalid_event"


def test_cancellation_leaves_lease_for_recovery(settings):
    store = store_for(settings)

    async def cancelled(_event):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(run_once(store, cancelled))
    store.finish.assert_not_called()


def test_lost_lease_is_not_reported_as_saved(settings, capsys):
    store = store_for(settings)
    store.finish.return_value = False
    asyncio.run(run_once(store, demo_processor))
    assert "job_lease_lost" in capsys.readouterr().out


def test_idle_worker_can_stop_promptly(settings, monkeypatch):
    store = store_for(settings)
    store.claim.return_value = None
    monkeypatch.setattr("assistops.worker.JobStore", lambda _: store)
    settings.worker_poll_seconds = 30

    async def stop_idle():
        stop = asyncio.Event()
        task = asyncio.create_task(serve(settings, stop))
        await asyncio.sleep(0.03)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(stop_idle())
    store.finish.assert_not_called()


def test_graceful_stop_saves_current_work_before_exit(settings, monkeypatch):
    store = store_for(settings)
    monkeypatch.setattr("assistops.worker.JobStore", lambda _: store)

    async def exercise():
        stop = asyncio.Event()

        async def processing(event):
            stop.set()
            await asyncio.sleep(0.01)
            return await demo_processor(event)

        monkeypatch.setattr("assistops.worker.demo_processor", processing)
        await serve(settings, stop)

    asyncio.run(exercise())
    store.claim.assert_called_once()
    store.finish.assert_called_once()
    assert store.finish.call_args.kwargs["error"] is None


def test_worker_recovers_after_database_error(settings, monkeypatch, capsys):
    settings.worker_processor = "demo"
    settings.worker_poll_seconds = 0.1
    calls = []

    async def exercise():
        stop = asyncio.Event()

        async def process(_store, _processor):
            calls.append(1)
            if len(calls) == 1:
                raise psycopg.OperationalError("private-connection-string")
            stop.set()
            return False

        monkeypatch.setattr("assistops.worker.run_once", process)
        await asyncio.wait_for(serve(settings, stop), timeout=1)

    asyncio.run(exercise())
    assert len(calls) == 2
    assert "private-connection-string" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "options",
    [
        {"worker_lease_seconds": 20, "worker_timeout_seconds": 20},
        {"worker_processor": "demo", "environment": "production"},
        {"worker_max_attempts": 0},
    ],
)
def test_invalid_worker_configuration_rejected(options):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **options)
