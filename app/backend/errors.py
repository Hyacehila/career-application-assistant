"""Uniform error structure and error codes for the board API."""

from __future__ import annotations

from typing import Any

# Error codes
CODE_BAD_REQUEST = "bad_request"
CODE_HOST_NOT_ALLOWED = "host_not_allowed"
CODE_ORIGIN_NOT_ALLOWED = "origin_not_allowed"
CODE_NOT_JSON = "not_json"
CODE_NOT_FOUND = "application_not_found"
CODE_VALIDATION = "validation_error"
CODE_MATCH_CONFLICT = "application_match_conflict"
CODE_STAGE_CONFLICT = "stage_conflict"
CODE_DATABASE_UNAVAILABLE = "database_unavailable"
CODE_UNKNOWN = "unknown_error"


class ApiError(Exception):
    """Application error mapped to a JSON error response."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def host_not_allowed(host: str) -> ApiError:
    return ApiError(
        400,
        CODE_HOST_NOT_ALLOWED,
        "Host is not allowed; the API only accepts loopback hosts.",
        {"host": host},
    )


def origin_not_allowed() -> ApiError:
    return ApiError(
        403,
        CODE_ORIGIN_NOT_ALLOWED,
        "Browser write requests must use the same loopback origin.",
    )


def not_json() -> ApiError:
    return ApiError(
        415,
        CODE_NOT_JSON,
        "Write requests must send a JSON body.",
    )


def not_found() -> ApiError:
    return ApiError(404, CODE_NOT_FOUND, "Application record not found.")


def validation_error(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(422, CODE_VALIDATION, message, details)


def match_conflict(candidate_count: int) -> ApiError:
    return ApiError(
        409,
        CODE_MATCH_CONFLICT,
        "Multiple application records matched; a human must choose.",
        {"candidate_count": candidate_count},
    )


def stage_conflict(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(409, CODE_STAGE_CONFLICT, message, details)


def database_unavailable(message: str) -> ApiError:
    return ApiError(503, CODE_DATABASE_UNAVAILABLE, message)
