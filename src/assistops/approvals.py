"""Signed human review endpoints; the model cannot approve its own proposals."""

from typing import Literal

import psycopg
import structlog
from fastapi import APIRouter, Request
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from assistops.business import BusinessTools
from assistops.events import EventError, ScopedInput, authenticated_input, signed_request_schema

router = APIRouter(prefix="/v1/approvals", tags=["approvals"])
logger = structlog.get_logger()


class ApprovalQuery(ScopedInput):
    proposal_id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )


class ApprovalDecision(ApprovalQuery):
    decision: Literal["approved", "rejected"]
    arguments_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


async def review(request: Request, schema):
    query, connector = await authenticated_input(request, schema)
    try:
        return await run_in_threadpool(
            BusinessTools(request.app.state.settings).review,
            query,
            connector,
            request.state.correlation_id,
            getattr(query, "decision", None),
        )
    except psycopg.Error as exc:
        logger.warning("approval_storage_unavailable", error_type=type(exc).__name__)
        raise EventError(503, "storage_unavailable") from exc


@router.post(
    "/status",
    summary="Review a proposal using a signed identity",
    openapi_extra=signed_request_schema(ApprovalQuery),
)
async def approval_status(request: Request):
    return await review(request, ApprovalQuery)


@router.post(
    "/decide",
    summary="Approve or reject the exact reviewed proposal",
    openapi_extra=signed_request_schema(ApprovalDecision),
)
async def approval_decide(request: Request):
    return await review(request, ApprovalDecision)
