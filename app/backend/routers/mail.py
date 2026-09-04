"""Mailbox account, sync operation, and structured candidate endpoints."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from .. import store as application_store
from ..errors import validation_error
from ..mail import outlook_connector, store
from ..mail.schemas import (
    ImapConnectRequest,
    MailAccountOut,
    MailAccountsOut,
    MailCandidateCommitOut,
    MailCandidateConfirmRequest,
    MailCandidateListOut,
    MailOperationAccepted,
    MailOperationOut,
    OutlookHeaderBatchOut,
    OutlookHeaderBatchRequest,
    OutlookMessageBatchOut,
    OutlookMessageBatchRequest,
    OutlookRunCompleteOut,
    OutlookRunCompleteRequest,
    OutlookRunFailOut,
    OutlookRunFailRequest,
    OutlookRunStartOut,
)

router = APIRouter(prefix="/api/mail", tags=["mail"])


@contextmanager
def _outlook_write(request: Request):
    """Serialize connector state changes so one lease is truly exclusive."""

    with application_store.open_connection_tx(request.app.state.paths) as connection:
        connection.execute("BEGIN IMMEDIATE")
        yield connection


def _imap_provider(value: str) -> str:
    if value not in store.PROVIDERS:
        raise validation_error("Unknown mail provider.")
    return value


@router.get("/accounts", response_model=MailAccountsOut)
async def list_accounts(request: Request) -> MailAccountsOut:
    paths = request.app.state.paths
    with application_store.open_connection_tx(paths) as connection:
        store.expire_pending_candidates(connection)
        outlook = outlook_connector.account_out(connection)
        rows = store.list_account_rows(connection)
    service = request.app.state.mail_service
    items: list[MailAccountOut] = [outlook]
    for row in rows:
        items.append(
            MailAccountOut(
                provider=row["provider"],
                connection_mode="local_imap",
                status=row["status"],
                masked_address=await service.masked_address(row["provider"]),
                history_window=row.get("history_window") or "new_only",
                last_attempt_at=row.get("last_attempt_at"),
                last_success_at=row.get("last_success_at"),
                next_retry_at=row.get("next_retry_at"),
                error_code=row.get("last_error_code"),
                pending_count=int(row.get("pending_count") or 0),
            )
        )
    return MailAccountsOut(
        items=items,
        pending_count=sum(item.pending_count for item in items),
    )


@router.post("/accounts/{provider}/connect", status_code=202, response_model=MailOperationAccepted)
async def connect_imap(
    request: Request, provider: str, payload: ImapConnectRequest
) -> MailOperationAccepted:
    provider = _imap_provider(provider)
    operation = request.app.state.mail_service.start_connect(provider, payload)
    return MailOperationAccepted(operation_id=operation.id)


@router.get("/operations/{operation_id}", response_model=MailOperationOut)
async def get_operation(request: Request, operation_id: str) -> MailOperationOut:
    return request.app.state.mail_service.get_operation(operation_id)


@router.post("/accounts/{provider}/sync", status_code=202, response_model=MailOperationAccepted)
async def sync_account(request: Request, provider: str) -> MailOperationAccepted:
    operation = request.app.state.mail_service.start_sync(_imap_provider(provider))
    return MailOperationAccepted(operation_id=operation.id)


@router.post("/accounts/{provider}/pause", response_model=MailAccountOut)
async def pause_account(request: Request, provider: str) -> MailAccountOut:
    if provider == "outlook":
        with _outlook_write(request) as connection:
            return outlook_connector.pause(connection)
    return await request.app.state.mail_service.pause(_imap_provider(provider))


@router.post("/accounts/{provider}/resume", response_model=MailAccountOut)
async def resume_account(request: Request, provider: str) -> MailAccountOut:
    if provider == "outlook":
        with _outlook_write(request) as connection:
            return outlook_connector.resume(connection)
    return await request.app.state.mail_service.resume(_imap_provider(provider))


@router.delete("/accounts/{provider}", status_code=204)
async def disconnect_account(request: Request, provider: str) -> Response:
    await request.app.state.mail_service.disconnect(_imap_provider(provider))
    return Response(status_code=204)


@router.post("/outlook-connector/runs", response_model=OutlookRunStartOut)
def start_outlook_connector_run(request: Request) -> OutlookRunStartOut:
    with _outlook_write(request) as connection:
        return outlook_connector.start_run(connection)


@router.post(
    "/outlook-connector/runs/{run_id}/headers", response_model=OutlookHeaderBatchOut
)
def register_outlook_connector_headers(
    request: Request, run_id: str, payload: OutlookHeaderBatchRequest
) -> OutlookHeaderBatchOut:
    with _outlook_write(request) as connection:
        return outlook_connector.register_headers(connection, run_id, payload)


@router.post(
    "/outlook-connector/runs/{run_id}/messages", response_model=OutlookMessageBatchOut
)
def ingest_outlook_connector_messages(
    request: Request, run_id: str, payload: OutlookMessageBatchRequest
) -> OutlookMessageBatchOut:
    with _outlook_write(request) as connection:
        return outlook_connector.ingest_messages(connection, run_id, payload)


@router.post(
    "/outlook-connector/runs/{run_id}/complete", response_model=OutlookRunCompleteOut
)
def complete_outlook_connector_run(
    request: Request, run_id: str, payload: OutlookRunCompleteRequest
) -> OutlookRunCompleteOut:
    with _outlook_write(request) as connection:
        return outlook_connector.complete_run(connection, run_id, payload)


@router.post(
    "/outlook-connector/runs/{run_id}/fail", response_model=OutlookRunFailOut
)
def fail_outlook_connector_run(
    request: Request, run_id: str, payload: OutlookRunFailRequest
) -> OutlookRunFailOut:
    with _outlook_write(request) as connection:
        return outlook_connector.fail_run(connection, run_id, payload)


@router.get("/candidates", response_model=MailCandidateListOut)
def list_candidates(
    request: Request,
    state: Literal["pending", "committed", "dismissed", "expired", "duplicate"] = "pending",
    limit: int = Query(default=100, ge=1, le=200),
) -> MailCandidateListOut:
    paths = request.app.state.paths
    with application_store.open_connection_tx(paths) as connection:
        items, total = store.list_candidates(connection, state=state, limit=limit)
    return MailCandidateListOut(items=items, total=total)


@router.post("/candidates/{candidate_id}/confirm", response_model=MailCandidateCommitOut)
def confirm_candidate(
    request: Request,
    candidate_id: int,
    payload: MailCandidateConfirmRequest,
) -> MailCandidateCommitOut:
    paths = request.app.state.paths
    with application_store.open_connection_tx(paths) as connection:
        candidate, application, event = store.confirm_candidate(
            connection, candidate_id, payload
        )
    return MailCandidateCommitOut(
        candidate=candidate,
        application=application,
        event=event,
    )


@router.post("/candidates/{candidate_id}/dismiss", status_code=204)
def dismiss_candidate(request: Request, candidate_id: int) -> Response:
    paths = request.app.state.paths
    with application_store.open_connection_tx(paths) as connection:
        store.dismiss_candidate(connection, candidate_id)
    return Response(status_code=204)
