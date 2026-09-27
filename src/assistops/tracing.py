"""Explicit, content-free LangSmith spans; telemetry never controls business execution."""

import asyncio
import hashlib
import inspect
import math
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from queue import Empty, Full, Queue
from threading import Event, Thread
from uuid import UUID, uuid4

import requests
import structlog
from langsmith import Client, tracing_context
from urllib3.util import Retry

logger = structlog.get_logger()
_exporter = ContextVar("assistops_trace_exporter", default=None)
_current = ContextVar("assistops_trace_span", default=None)
OUTCOMES = frozenset(
    {
        "answered",
        "abstained",
        "denied",
        "rejected",
        "unavailable",
        "read_completed",
        "awaiting_approval",
        "ticket_pending",
        "ticket_created",
        "ticket_failed",
        "ticket_uncertain",
        "clarification_required",
        "expired",
        "acknowledged",
    }
)
NAMES = {
    "worker": "chain",
    "supervisor": "chain",
    "route": "chain",
    "rag": "chain",
    "retrieve": "retriever",
    "tools": "tool",
    "generation": "llm",
}


def safe_metadata(values):
    """Allow values by type AND vocabulary, not just by field name."""
    safe = {"redaction_policy": "metrics-only-v1"}
    for key in ("attempt", "context_turns", "input_tokens", "output_tokens", "embedding_tokens"):
        value = values.get(key)
        if type(value) is int and 0 <= value <= 10**9:
            safe[key] = value
    for key in ("reused_plan", "job_saved"):
        if type(values.get(key)) is bool:
            safe[key] = values[key]
    if isinstance(values.get("outcome"), str) and values["outcome"] in OUTCOMES:
        safe["outcome"] = values["outcome"]
    with suppress(ValueError, KeyError):
        safe["event_id"] = str(UUID(str(values["event_id"])))
    cost = values.get("estimated_cost_usd")
    if type(cost) in (float, int) and 0 <= cost <= 1000 and math.isfinite(cost):
        safe["estimated_cost_usd"] = cost
    value = values.get("correlation_ref", "")
    if isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value):
        safe["correlation_ref"] = value
    if values.get("ls_provider") == "openai":
        safe["ls_provider"] = "openai"
    if values.get("ls_model_name") == "gpt-4.1-mini-2025-04-14":
        safe["ls_model_name"] = values["ls_model_name"]
    usage = values.get("usage_metadata")
    if isinstance(usage, dict):
        counts = {
            k: usage[k]
            for k in ("input_tokens", "output_tokens")
            if type(usage.get(k)) is int and 0 <= usage[k] <= 10**9
        }
        if len(counts) == 2:
            safe["usage_metadata"] = {**counts, "total_tokens": sum(counts.values())}
    return safe


class TraceSession(requests.Session):
    def request(self, *args, **kwargs):
        # A redirect must not forward the SDK's custom x-api-key header elsewhere.
        kwargs["allow_redirects"] = False
        response = super().request(*args, **kwargs)
        if 300 <= response.status_code < 400:
            raise requests.HTTPError("Tracing endpoint redirects are not supported")
        return response


class TraceExporter:
    def __init__(self, settings, client_factory=Client):
        self.project = settings.langsmith_project
        self.client = client_factory(
            api_url=settings.langsmith_endpoint,
            api_key=settings.langsmith_api_key.get_secret_value()
            if settings.langsmith_api_key
            else "",
            auto_batch_tracing=False,
            hide_inputs=True,
            hide_outputs=True,
            hide_metadata=safe_metadata,
            omit_traced_runtime_info=True,
            tracing_sampling_rate=1,
            tracing_mode="langsmith",
            timeout_ms=(500, 1500),
            retry_config=Retry(total=0),
            session=TraceSession(),
        )
        # Queue holds only sanitized spans, never request objects or provider responses.
        self.queue = Queue(maxsize=256)
        self.stopped = Event()
        self.sent = self.failed = self.dropped = 0
        self.thread = Thread(target=self._send, daemon=True, name="assistops-traces")
        self.thread.start()

    def submit(self, payload):
        try:
            self.queue.put_nowait(payload)
            return True
        except Full:
            self.dropped += 1
            if self.dropped == 1:
                logger.warning("tracing_queue_full")
            return False

    def _send(self):
        try:
            while not self.stopped.is_set() or not self.queue.empty():
                try:
                    payload = self.queue.get(timeout=0.1)
                except Empty:
                    continue
                try:
                    self.client.create_run(project_name=self.project, **payload)
                    self.sent += 1
                except Exception:
                    self.failed += 1
                    if self.failed == 1:
                        # Exception strings can include credentials or HTTP response bodies.
                        logger.warning("tracing_export_failed")
                finally:
                    self.queue.task_done()
        finally:
            try:
                self.client.session.close()
            except Exception:
                logger.warning("tracing_close_failed")

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            logger.warning("tracing_flush_incomplete")


@contextmanager
def tracing_session(settings, client_factory=Client):
    exporter = None
    if settings.langsmith_enabled:
        try:
            exporter = TraceExporter(settings, client_factory)
        except Exception:
            logger.warning("tracing_initialization_failed")
    token = _exporter.set(exporter)
    # Disable ambient LangChain tracing: raw graph state must never be captured automatically.
    try:
        with tracing_context(enabled=False):
            yield exporter
    finally:
        _exporter.reset(token)
        if exporter:
            exporter.close()


class Span:
    def __init__(self, name, parent, metadata):
        self.name, self.parent = name, parent
        self.id, self.start = uuid4(), datetime.now(UTC)
        segment = self.start.strftime("%Y%m%dT%H%M%S%fZ") + str(self.id)
        self.order = parent.order + "." + segment if parent else segment
        self.trace_id = parent.trace_id if parent else self.id
        inherited = {
            k: parent.metadata[k]
            for k in ("event_id", "correlation_ref", "attempt")
            if parent and k in parent.metadata
        }
        self.metadata = safe_metadata({**inherited, **metadata})
        self.error = None

    def record(self, result):
        if not isinstance(result, dict):
            return
        selected = {
            k: result[k]
            for k in ("outcome", "reused_plan", "context_turns", "job_saved")
            if k in result
        }
        if self.name == "generation":
            selected.update(ls_provider="openai", ls_model_name="gpt-4.1-mini-2025-04-14")
            selected["usage_metadata"] = result.get("usage")
        if self.name == "rag" and isinstance(result.get("usage"), dict):
            selected.update(
                {
                    k: result["usage"][k]
                    for k in (
                        "input_tokens",
                        "output_tokens",
                        "embedding_tokens",
                        "estimated_cost_usd",
                    )
                    if k in result["usage"]
                }
            )
        self.metadata = safe_metadata({**self.metadata, **selected})
        if self.metadata.get("outcome") in {"unavailable", "ticket_failed", "ticket_uncertain"}:
            self.error = "operation_unavailable"


@contextmanager
def span(name, **metadata):
    exporter = _exporter.get()
    if exporter is None:
        yield None
        return
    current = Span(name, _current.get(), metadata)
    token = _current.set(current)
    try:
        yield current
    except BaseException as exc:
        current.error = (
            "cancelled" if isinstance(exc, asyncio.CancelledError) else "operation_failed"
        )
        raise
    finally:
        _current.reset(token)
        queued = exporter.submit(
            {
                "id": current.id,
                "name": name,
                "run_type": NAMES[name],
                "trace_id": current.trace_id,
                "dotted_order": current.order,
                "parent_run_id": current.parent.id if current.parent else None,
                "start_time": current.start,
                "end_time": datetime.now(UTC),
                "inputs": {},
                "outputs": {},
                "extra": {"metadata": current.metadata},
                "error": current.error,
            }
        )
        if queued and current.parent is None:
            logger.info(
                "trace_queued", trace_id=str(current.id), event_id=current.metadata.get("event_id")
            )


def record(result):
    current = _current.get()
    if current:
        current.record(result)


def correlation_ref(value):
    # Incoming correlation IDs are caller-controlled and may contain personal data.
    return hashlib.sha256(value.encode()).hexdigest()


def traced(name):
    if name not in NAMES:
        raise ValueError("Unknown trace operation")

    def decorate(function):
        if inspect.iscoroutinefunction(function):

            @wraps(function)
            async def async_call(*args, **kwargs):
                with span(name):
                    result = await function(*args, **kwargs)
                    record(result)
                    return result

            return async_call

        @wraps(function)
        def sync_call(*args, **kwargs):
            with span(name):
                result = function(*args, **kwargs)
                record(result)
                return result

        return sync_call

    return decorate
