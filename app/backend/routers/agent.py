"""Agent-only endpoints: form-fill callback and structured status update."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..schemas import AgentFillCompleted, AgentStatusUpdate
from .. import store

router = APIRouter(tags=["agent"])


@router.post("/api/agent/fill-completed", status_code=201)
def fill_completed(request: Request, payload: AgentFillCompleted) -> JSONResponse:
    """Create or idempotently update a pending_review record after a form fill.

    Never moves an application backwards or marks it applied.
    """

    paths = request.app.state.paths
    fields = payload.model_dump()
    with store.open_connection_tx(paths) as connection:
        record = store.agent_fill_completed(connection, fields)
        return JSONResponse(status_code=201, content=record.model_dump())


@router.post("/api/agent/status-update")
def status_update(request: Request, payload: AgentStatusUpdate) -> JSONResponse:
    """Append a validated stage event to a uniquely matched application."""

    paths = request.app.state.paths
    with store.open_connection_tx(paths) as connection:
        record, event = store.agent_status_update(
            connection, payload.match.model_dump(exclude_none=True), payload.event
        )
        return JSONResponse(
            content={"application": record.model_dump(), "event": event.model_dump()}
        )
