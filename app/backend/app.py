"""FastAPI application factory for the local board service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Paths, default_paths
from .database import DatabaseUnavailableError
from .errors import ApiError, CODE_UNKNOWN, host_not_allowed, not_json
from .migrations import SchemaVersionError, ensure_migrations

ALLOWED_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _hostname_from_header(value: str) -> str:
    """Return a normalized hostname without a port, including IPv6 literals."""

    try:
        return (urlsplit(f"//{value}").hostname or "").casefold()
    except ValueError:
        return value.casefold()


class RequestGuard(BaseHTTPMiddleware):
    """Reject non-loopback hosts and non-JSON write requests."""

    async def dispatch(self, request: Request, call_next):
        host = _hostname_from_header(request.headers.get("host") or "")
        if host and host not in ALLOWED_HOSTS:
            return JSONResponse(status_code=400, content=_error_body(host_not_allowed(host)))
        if request.method in {"POST", "PATCH"}:
            content_type = (request.headers.get("content-type") or "").lower()
            if not content_type.startswith("application/json"):
                return JSONResponse(status_code=415, content=_error_body(not_json()))
        return await call_next(request)


def _error_body(error: ApiError) -> dict:
    body: dict = {"code": error.code, "message": error.message}
    if error.details:
        body["details"] = error.details
    return body


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    yield


def create_app(db_path: Path | None = None) -> FastAPI:
    """Build the board API.

    ``db_path`` injects a temporary database for tests; the production
    entrypoint always uses ``private/applications.sqlite``.
    """

    if db_path is not None:
        paths = Paths(
            repository_root=db_path.parent.parent,
            private_root=db_path.parent,
        )
    else:
        paths = default_paths()

    app = FastAPI(title="Career Application Board", lifespan=_lifespan)
    app.state.paths = paths
    app.add_middleware(RequestGuard)

    from .routers import agent, applications, health

    app.include_router(health.router)
    app.include_router(applications.router)
    app.include_router(agent.router)

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc))

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = {
            "errors": [
                {
                    "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
                    "message": error.get("msg", "Invalid value."),
                    "type": error.get("type", "validation_error"),
                }
                for error in exc.errors()
            ]
        }
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Request validation failed.",
                "details": details,
            },
        )

    @app.exception_handler(DatabaseUnavailableError)
    async def database_error_handler(_: Request, exc: DatabaseUnavailableError) -> JSONResponse:
        from .errors import database_unavailable

        return JSONResponse(status_code=503, content=_error_body(database_unavailable(str(exc))))

    @app.exception_handler(SchemaVersionError)
    async def schema_error_handler(_: Request, exc: SchemaVersionError) -> JSONResponse:
        from .errors import database_unavailable

        return JSONResponse(status_code=503, content=_error_body(database_unavailable(str(exc))))

    @app.exception_handler(Exception)
    async def unknown_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("board").exception(
            "Unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500, content={"code": CODE_UNKNOWN, "message": "Unexpected server error."}
        )

    dist = paths.frontend_dist
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


def init_database(paths: Paths) -> None:
    """Create or migrate the fixed database before serving."""

    from .database import open_connection
    from .migrations import get_schema_version

    connection = open_connection(paths)
    try:
        with connection:
            ensure_migrations(connection)
    finally:
        connection.close()

    connection = open_connection(paths)
    try:
        version = get_schema_version(connection)
    finally:
        connection.close()
    if version != 1:
        raise SchemaVersionError("Schema migration did not reach version 1.")
