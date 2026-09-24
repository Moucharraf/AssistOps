import asyncio
import hashlib
import hmac
import json
import re
import time
from typing import Annotated, Literal
from uuid import UUID

import psycopg
import structlog
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool

router = APIRouter()
logger = structlog.get_logger()
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
MAX_BODY_BYTES = 64 * 1024


class ScopedInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    tenant_id: Identifier
    user_id: Identifier
    source: Literal["webhook", "slack", "email"]


class EventInput(ScopedInput):
    event_id: Identifier
    conversation_id: Identifier
    message: str = Field(min_length=1, max_length=16000)

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank")
        if "\x00" in value:
            raise ValueError("Null characters are not supported")
        value.encode("utf-8")
        return value


class Receipt(BaseModel):
    receipt_id: UUID
    event_id: str
    status: Literal["received"] = "received"
    duplicate: bool


class StatusQuery(ScopedInput):
    receipt_id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )


class JobStatus(BaseModel):
    receipt_id: UUID
    status: Literal["pending", "processing", "completed", "failed"]
    attempts: int
    result: dict | None
    last_error: str | None


class EventError(Exception):
    def __init__(self, status: int, code: str):
        self.status = status
        self.code = code


def verify_signature(secret: str, timestamp: str, signature: str, body: bytes) -> None:
    if not re.fullmatch(r"[0-9]{1,12}", timestamp):
        raise EventError(401, "invalid_signature")
    if abs(time.time() - int(timestamp)) > 300:
        raise EventError(401, "invalid_signature")
    expected = (
        "v1="
        + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    )
    if not hmac.compare_digest(expected.encode(), signature.encode()):
        raise EventError(401, "invalid_signature")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


@router.post(
    "/v1/events",
    status_code=202,
    response_model=Receipt,
    tags=["events"],
    summary="Accept a signed event into the durable inbox",
    description="Persists the event and pending job. Does not execute business actions.",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": EventInput.model_json_schema()}},
        },
        "parameters": [
            {"name": name, "in": "header", "required": True, "schema": {"type": "string"}}
            for name in ("X-AssistOps-Connector", "X-AssistOps-Timestamp", "X-AssistOps-Signature")
        ],
    },
)
async def receive_event(request: Request) -> Receipt:
    event, connector_id = await authenticated_input(request, EventInput)
    try:
        return await run_in_threadpool(
            request.app.state.event_store.accept, event, connector_id, request.state.correlation_id
        )
    except psycopg.Error as exc:
        logger.warning("event_storage_unavailable", error_type=type(exc).__name__)
        raise EventError(503, "storage_unavailable") from exc


@router.post(
    "/v1/events/status",
    response_model=JobStatus,
    tags=["events"],
    summary="Read job status using a signed, identity-scoped query",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": StatusQuery.model_json_schema()}},
        },
        "parameters": [
            {"name": name, "in": "header", "required": True, "schema": {"type": "string"}}
            for name in ("X-AssistOps-Connector", "X-AssistOps-Timestamp", "X-AssistOps-Signature")
        ],
    },
)
async def event_status(request: Request) -> JobStatus:
    query, connector_id = await authenticated_input(request, StatusQuery)
    try:
        result = await run_in_threadpool(request.app.state.event_store.status, query, connector_id)
    except psycopg.Error as exc:
        logger.warning("event_storage_unavailable", error_type=type(exc).__name__)
        raise EventError(503, "storage_unavailable") from exc
    if result is None:
        raise EventError(404, "event_not_found")
    return result


async def authenticated_input(request: Request, schema):
    settings = request.app.state.settings
    if not settings.webhook_connectors:
        raise EventError(503, "webhooks_not_configured")
    # Each connector attests only configured tenants, sources and user identities.
    headers = {}
    for name in ("X-AssistOps-Connector", "X-AssistOps-Timestamp", "X-AssistOps-Signature"):
        values = request.headers.getlist(name)
        if len(values) != 1 or len(values[0]) > 256:
            raise EventError(401, "invalid_signature")
        headers[name] = values[0]
    connector_id = headers["X-AssistOps-Connector"]
    connector = settings.webhook_connectors.get(connector_id)
    if connector is None:
        raise EventError(401, "invalid_signature")
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise EventError(415, "unsupported_media_type")
    if request.headers.get("content-encoding", "identity") != "identity":
        raise EventError(415, "unsupported_encoding")
    body = bytearray()
    try:
        async with asyncio.timeout(settings.webhook_body_timeout_seconds):
            async for chunk in request.stream():
                if len(body) + len(chunk) > MAX_BODY_BYTES:
                    raise EventError(413, "body_too_large")
                body.extend(chunk)
    except TimeoutError as exc:
        raise EventError(408, "body_timeout") from exc
    verify_signature(
        connector.secret.get_secret_value(),
        headers["X-AssistOps-Timestamp"],
        headers["X-AssistOps-Signature"],
        bytes(body),
    )
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=unique_object)
        event = schema.model_validate(data)
    except (ValueError, ValidationError, RecursionError) as exc:
        raise EventError(422, "invalid_event") from exc
    if (
        event.tenant_id != connector.tenant_id
        or event.source != connector.source
        or event.user_id not in connector.allowed_user_ids
    ):
        raise EventError(403, "identity_not_allowed")
    return event, connector_id
