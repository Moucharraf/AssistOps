"""Same-origin browser interface over the existing human approval service."""

import asyncio
import hmac
import json
from importlib.resources import files
from typing import Literal
from uuid import UUID

import psycopg
import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from starlette.concurrency import run_in_threadpool

from assistops.approvals import ApprovalDecision, ApprovalQuery
from assistops.business import BusinessTools
from assistops.events import EventError, unique_object
from assistops.review import auth as review_auth
from assistops.storage import connect

router = APIRouter(prefix="/review", tags=["review UI"])
logger = structlog.get_logger()


def cookie_name(settings):
    return (
        "__Host-assistops_review"
        if settings.review_ui_origin.startswith("https:")
        else ("assistops_review")
    )


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    username: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{2,63}$")
    password: SecretStr = Field(min_length=1, max_length=256)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    decision: Literal["approved", "rejected"]
    arguments_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


async def database_call(function, *args):
    try:
        return await run_in_threadpool(function, *args)
    except psycopg.Error as exc:
        logger.warning("review_storage_unavailable", error_type=type(exc).__name__)
        raise EventError(503, "storage_unavailable") from exc


def require_origin(request):
    # Do not derive the trusted origin from Host or X-Forwarded-Host headers.
    if (
        request.headers.getlist("origin") != [request.app.state.settings.review_ui_origin]
        or request.headers.get("x-assistops-ui") != "1"
    ):
        raise EventError(403, "invalid_origin")


async def body(request, schema):
    require_origin(request)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise EventError(415, "unsupported_media_type")
    if request.headers.get("content-encoding", "identity") != "identity":
        raise EventError(415, "unsupported_encoding")
    content = bytearray()
    try:
        async with asyncio.timeout(5):
            async for chunk in request.stream():
                if len(content) + len(chunk) > 4096:
                    raise EventError(413, "body_too_large")
                content.extend(chunk)
        return schema.model_validate(json.loads(content, object_pairs_hook=unique_object))
    except TimeoutError as exc:
        raise EventError(408, "body_timeout") from exc
    except (ValueError, ValidationError) as exc:
        raise EventError(422, "invalid_request") from exc


async def identity(request, *, mutation=False):
    settings = request.app.state.settings
    account = await database_call(
        review_auth.authenticate, settings, request.cookies.get(cookie_name(settings))
    )
    if mutation:
        require_origin(request)
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied.encode(), account["csrf_token"].encode()):
            raise EventError(403, "invalid_csrf")
    return account


@router.get("", include_in_schema=False)
async def index():
    return Response(
        files("assistops.review").joinpath("static/index.html").read_bytes(),
        media_type="text/html",
    )


@router.get("/assets/{name}", include_in_schema=False)
async def asset(name: Literal["app.js", "style.css"]):
    return Response(
        files("assistops.review").joinpath(f"static/{name}").read_bytes(),
        media_type="text/javascript" if name.endswith(".js") else "text/css",
    )


@router.post("/api/login")
async def login(request: Request):
    data = await body(request, LoginInput)
    settings = request.app.state.settings
    token = await database_call(
        review_auth.login,
        settings,
        data.username,
        data.password.get_secret_value(),
        request.client.host if request.client else "unknown",
    )
    # A new login rotates the browser's existing session instead of leaving it usable.
    previous = request.cookies.get(cookie_name(settings))
    if previous:
        await database_call(review_auth.logout, settings, previous)
    response = Response(status_code=204)
    response.set_cookie(
        cookie_name(settings),
        token,
        max_age=settings.review_session_seconds,
        httponly=True,
        secure=settings.review_ui_origin.startswith("https:"),
        samesite="strict",
        path="/",
    )
    logger.info("review_login_succeeded", actor_id=data.username)
    return response


@router.get("/api/session")
async def session(request: Request):
    account = await identity(request)
    return {key: account[key] for key in ("username", "user_id", "tenant_id", "csrf_token")}


@router.post("/api/logout")
async def logout(request: Request):
    await identity(request, mutation=True)
    settings = request.app.state.settings
    await database_call(review_auth.logout, settings, request.cookies[cookie_name(settings)])
    response = Response(status_code=204)
    response.delete_cookie(
        cookie_name(settings),
        path="/",
        httponly=True,
        secure=settings.review_ui_origin.startswith("https:"),
        samesite="strict",
    )
    return response


def list_proposals(settings, account, status, page):
    BusinessTools(settings).enabled()
    with connect(settings) as connection, connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            """SELECT p.id, p.arguments->>'subject' AS subject,
                      CASE WHEN p.status = 'pending' AND p.expires_at <= clock_timestamp()
                           THEN 'expired' ELSE p.status END AS status,
                      p.created_at, p.expires_at, e.payload->>'user_id' AS requester_id,
                      e.connector_id, d.status AS delivery_status,
                      p.arguments->'ticket_target'->>'provider' AS provider
               FROM ticket_proposals p JOIN inbound_events e ON e.id = p.event_id
               LEFT JOIN ticket_deliveries d ON d.proposal_id = p.id
               WHERE e.tenant_id = %s AND e.connector_id = ANY(%s)
                 AND (%s = 'all' OR (p.status = 'pending' AND p.expires_at > clock_timestamp()))
               ORDER BY p.created_at DESC, p.id DESC LIMIT 26 OFFSET %s""",
            (account["tenant_id"], account["connector_ids"], status, page * 25),
        ).fetchall()
    return {"items": rows[:25], "has_more": len(rows) > 25, "page": page}


@router.get("/api/proposals")
async def proposals(
    request: Request,
    status: Literal["pending", "all"] = "pending",
    page: int = Query(default=0, ge=0, le=10000),
):
    account = await identity(request)
    return await database_call(list_proposals, request.app.state.settings, account, status, page)


def review_proposal(settings, account, proposal_id, correlation_id, decision=None):
    with connect(settings) as connection, connection.cursor(row_factory=dict_row) as cursor:
        proposal = cursor.execute(
            """SELECT e.connector_id, e.source, e.payload->>'user_id' AS requester_id,
                      p.created_at, p.decided_at, e.payload->>'message' AS request_message
               FROM ticket_proposals p JOIN inbound_events e ON e.id = p.event_id
               WHERE p.id = %s AND e.tenant_id = %s AND e.connector_id = ANY(%s)""",
            (proposal_id, account["tenant_id"], account["connector_ids"]),
        ).fetchone()
    if (
        proposal is None
        or settings.webhook_connectors[proposal["connector_id"]].source != proposal["source"]
    ):
        raise EventError(404, "proposal_not_found")
    scope = dict(
        proposal_id=str(proposal_id),
        tenant_id=account["tenant_id"],
        user_id=account["user_id"],
        source=proposal["source"],
    )
    query = (
        ApprovalDecision(**scope, **decision.model_dump()) if decision else ApprovalQuery(**scope)
    )
    result = BusinessTools(settings).review(
        query, proposal["connector_id"], correlation_id, decision.decision if decision else None
    )
    return {
        **result,
        "requester_id": proposal["requester_id"],
        "connector_id": proposal["connector_id"],
        "created_at": proposal["created_at"],
        "request_message": proposal["request_message"],
        "can_decide": result["proposal"]["status"] == "pending"
        and proposal["requester_id"] != account["user_id"],
    }


@router.get("/api/proposals/{proposal_id}")
async def detail(request: Request, proposal_id: UUID):
    account = await identity(request)
    return await database_call(
        review_proposal,
        request.app.state.settings,
        account,
        proposal_id,
        request.state.correlation_id,
    )


@router.post("/api/proposals/{proposal_id}/decision")
async def decide(request: Request, proposal_id: UUID):
    account = await identity(request, mutation=True)
    data = await body(request, DecisionInput)
    return await database_call(
        review_proposal,
        request.app.state.settings,
        account,
        proposal_id,
        request.state.correlation_id,
        data,
    )
