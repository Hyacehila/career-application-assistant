"""Health endpoint for the board service."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..database import open_connection
from ..migrations import SUPPORTED_SCHEMA_VERSION, get_schema_version

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(request: Request) -> JSONResponse:
    paths = request.app.state.paths
    connection = None
    try:
        connection = open_connection(paths)
        version = get_schema_version(connection)
        if version != SUPPORTED_SCHEMA_VERSION:
            raise RuntimeError("Unsupported database schema version.")
        status = "ok"
    except Exception:  # pragma: no cover - defensive
        status = "degraded"
    finally:
        if connection is not None:
            connection.close()

    body = {
        "status": status,
        "database": "available" if status == "ok" else "unavailable",
        "schema_version": version if status == "ok" else None,
    }
    return JSONResponse(status_code=200 if status == "ok" else 503, content=body)
