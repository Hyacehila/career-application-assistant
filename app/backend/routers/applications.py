"""Application CRUD and event timeline endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from ..database import open_connection
from ..schemas import (
    ApplicationBase,
    CreateApplication,
    CreateEvent,
    EventOut,
    ListResponse,
    PatchApplication,
    PatchEvent,
)
from .. import store

router = APIRouter(tags=["applications"])


@router.get("/api/applications")
def list_applications(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    stage_group: str | None = Query(default=None),
    status: str | None = Query(default=None),
    type: str | None = Query(default=None, max_length=100),
    city: str | None = Query(default=None, max_length=200),
    source: str | None = Query(default=None, max_length=100),
    sort: str = Query(default="updated_at", max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ListResponse:
    paths = request.app.state.paths
    connection = open_connection(paths)
    try:
        return store.list_applications(
            connection,
            q=q,
            stage_group=stage_group,
            status=status,
            application_type=type,
            city=city,
            source=source,
            sort=sort,
            page=page,
            page_size=page_size,
        )
    finally:
        connection.close()


@router.post("/api/applications", status_code=201)
def create_application(request: Request, payload: CreateApplication) -> ApplicationBase:
    paths = request.app.state.paths
    with store.open_connection_tx(paths) as connection:
        return store.create_application(connection, payload)


@router.get("/api/applications/{application_id}")
def get_application(request: Request, application_id: int) -> dict:
    paths = request.app.state.paths
    connection = open_connection(paths)
    try:
        record = store.get_application(connection, application_id)
        events = store.list_events(connection, application_id)
        return {"application": record, "events": [event.model_dump() for event in events]}
    finally:
        connection.close()


@router.patch("/api/applications/{application_id}")
def patch_application(request: Request, application_id: int, payload: PatchApplication) -> ApplicationBase:
    paths = request.app.state.paths
    with store.open_connection_tx(paths) as connection:
        return store.patch_application(connection, application_id, payload)


@router.delete("/api/applications/{application_id}", status_code=204)
def delete_application(request: Request, application_id: int) -> None:
    paths = request.app.state.paths
    with store.open_connection_tx(paths) as connection:
        store.soft_delete(connection, application_id)


@router.post("/api/applications/{application_id}/events", status_code=201)
def add_event(request: Request, application_id: int, payload: CreateEvent) -> JSONResponse:
    paths = request.app.state.paths
    with store.open_connection_tx(paths) as connection:
        record, event = store.add_event(connection, application_id, payload)
        return JSONResponse(
            status_code=201,
            content={"application": record.model_dump(), "event": event.model_dump()},
        )


@router.patch("/api/applications/{application_id}/events/{event_id}")
def patch_event(request: Request, application_id: int, event_id: int, payload: PatchEvent) -> EventOut:
    paths = request.app.state.paths
    with store.open_connection_tx(paths) as connection:
        return store.patch_event(connection, application_id, event_id, payload)
