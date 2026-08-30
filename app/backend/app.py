"""FastAPI application factory for the local board service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Paths, default_paths
from .database import DatabaseUnavailableError
from .errors import ApiError, CODE_UNKNOWN, host_not_allowed, not_json, origin_not_allowed
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
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if origin:
                try:
                    parsed_origin = urlsplit(origin)
                    origin_host = (parsed_origin.hostname or "").casefold()
                    request_port = urlsplit(f"//{request.headers.get('host') or ''}").port
                    origin_port = parsed_origin.port
                    effective_request_port = request_port or 80
                    effective_origin_port = origin_port or (443 if parsed_origin.scheme == "https" else 80)
                    same_origin = (
                        parsed_origin.scheme == "http"
                        and origin_host == host
                        and effective_origin_port == effective_request_port
                    )
                except ValueError:
                    same_origin = False
                if not same_origin:
                    error = origin_not_allowed()
                    return JSONResponse(status_code=error.status_code, content=_error_body(error))
        if request.method in {"POST", "PATCH", "PUT"}:
            content_type = (request.headers.get("content-type") or "").lower()
            if not content_type.startswith("application/json"):
                return JSONResponse(status_code=415, content=_error_body(not_json()))
        return await call_next(request)


def _error_body(error: ApiError) -> dict:
    body: dict = {"code": error.code, "message": error.message}
    if error.details:
        body["details"] = error.details
    return body


RuntimeMode = Literal["standard", "test", "demo"]


@asynccontextmanager
async def _mail_lifespan(app: FastAPI):
    service = app.state.mail_service
    await service.start()
    try:
        yield
    finally:
        await service.stop()


def _build_app(paths: Paths, mode: RuntimeMode) -> FastAPI:
    """Build one explicit runtime mode without weakening path boundaries."""

    mail_ingestion = mode != "demo"
    app = FastAPI(
        title="求职投递助手 / Career Application Assistant",
        lifespan=_mail_lifespan if mail_ingestion else None,
    )
    app.state.paths = paths
    app.state.mode = mode
    app.state.synthetic_data = mode == "demo"
    app.state.mail_ingestion = mail_ingestion
    if mail_ingestion:
        from .mail.service import MailService

        app.state.mail_service = MailService(paths, scheduler_enabled=mode == "standard")
    app.add_middleware(RequestGuard)

    from .routers import applications, health

    app.include_router(health.router)
    app.include_router(applications.router)
    if mode == "demo":
        from .routers import demo

        app.include_router(demo.router)
    else:
        from .routers import agent, mail

        app.include_router(agent.router)
        app.include_router(mail.router)

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

    @app.api_route(
        "/api/{unmatched_path:path}",
        methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def unknown_api_route(unmatched_path: str) -> JSONResponse:
        """Keep unknown API writes from falling through to the static-file mount."""

        del unmatched_path
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    dist = paths.frontend_dist
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app


def create_app() -> FastAPI:
    """Build the standard service at the fixed private/applications.sqlite path."""

    return _build_app(default_paths(), "standard")


def create_test_app(paths: Paths) -> FastAPI:
    """Build a test service with mail APIs enabled and its scheduler disabled."""

    return _build_app(paths, "test")


def create_demo_app(paths: Paths) -> FastAPI:
    """Build an isolated synthetic-data service with no mail or Agent APIs."""

    from .demo import validate_demo_paths

    validate_demo_paths(paths)
    return _build_app(paths, "demo")


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
    from .migrations import SUPPORTED_SCHEMA_VERSION

    if version != SUPPORTED_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Schema migration did not reach version {SUPPORTED_SCHEMA_VERSION}."
        )
