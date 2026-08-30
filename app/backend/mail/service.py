"""Background orchestration for read-only mailbox ingestion."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .. import store as application_store
from ..clock import CN_TZ, now_iso
from ..config import Paths
from ..database import open_connection
from ..errors import ApiError, validation_error
from . import store
from .classifier import classify_and_extract, is_likely_recruitment_header
from .credentials import (
    CredentialNotFound,
    CredentialStoreError,
    SecureStorageUnavailable,
    WindowsCredentialStore,
    default_msal_cache_path,
)
from .graph import (
    GraphAuthenticationRequired,
    GraphCursorExpired,
    GraphError,
    GraphMailClient,
    GraphMessageUnavailable,
    GraphPayloadTooLarge,
    GraphProtocolError,
    GraphThrottled,
    GraphTransientError,
    OutlookAuth,
)
from .imap import ImapConnector, ImapConnectorError, ImapCursor
from .schemas import (
    HistoryWindow,
    ImapConnectRequest,
    MailAccountOut,
    MailOperationOut,
    OutlookConnectRequest,
)

LOGGER = logging.getLogger("board.mail")
POLL_MINUTES = 5
BACKOFF_MINUTES = (5, 15, 30, 60)
MAX_CURSOR_REBUILD_DAYS = 90
OUTLOOK_STAGING_CACHE_RE = re.compile(
    r"^msal\.[0-9a-f]{32}\.(?:cache|backup)(?:\.lockfile)?$"
)


class MailServiceError(RuntimeError):
    """Sanitized service error safe for operation status and logs."""

    def __init__(self, code: str, *, auth_required: bool = False, retry_after: float | None = None):
        super().__init__(code)
        self.code = code
        self.auth_required = auth_required
        self.retry_after = retry_after


@dataclass(slots=True)
class _Operation:
    id: str
    provider: str
    kind: str
    status: str = "pending"
    error_code: str | None = None

    def public(self) -> MailOperationOut:
        return MailOperationOut(
            id=self.id,
            provider=self.provider,
            kind=self.kind,
            status=self.status,
            error_code=self.error_code,
        )


class MailService:
    """Own scheduler, secure credentials, and provider operation lifetimes."""

    def __init__(
        self,
        paths: Paths,
        *,
        scheduler_enabled: bool = True,
        credential_store_factory: Callable[[], Any] = WindowsCredentialStore,
        outlook_auth_factory: Callable[..., Any] = OutlookAuth,
        graph_client_factory: Callable[..., Any] = GraphMailClient,
        imap_connector_factory: Callable[..., Any] = ImapConnector,
        outlook_cache_path_factory: Callable[[], Path] | None = None,
    ) -> None:
        self.paths = paths
        self.scheduler_enabled = scheduler_enabled
        self._credential_store_factory = credential_store_factory
        self._outlook_auth_factory = outlook_auth_factory
        self._graph_client_factory = graph_client_factory
        self._imap_connector_factory = imap_connector_factory
        self._outlook_cache_path_factory = (
            outlook_cache_path_factory or default_msal_cache_path
        )
        self._outlook_startup_cleanup_enabled = (
            scheduler_enabled or outlook_cache_path_factory is not None
        )
        self._scheduler: Any | None = None
        self._operations: dict[str, _Operation] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._provider_operation: dict[str, str] = {}
        self._failure_counts: dict[str, int] = {}

    async def start(self) -> None:
        with application_store.open_connection_tx(self.paths) as connection:
            connection.execute(
                """
                UPDATE mail_accounts
                SET status = 'error', last_error_code = 'operation_interrupted',
                    updated_at = ?
                WHERE status = 'connecting'
                """,
                (now_iso(),),
            )
            store.expire_pending_candidates(connection)
        for provider in ("qq", "163"):
            await self._cleanup_stale_imap_credentials(provider)
        if self._outlook_startup_cleanup_enabled:
            try:
                await asyncio.to_thread(self._cleanup_outlook_staging_cache)
            except SecureStorageUnavailable:
                LOGGER.warning("mail_outlook_staging_cleanup_failed")
        if not self.scheduler_enabled:
            return
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler

            scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
            scheduler.add_job(
                self.poll_connected_accounts,
                "interval",
                minutes=POLL_MINUTES,
                id="mail-poll",
                coalesce=True,
                max_instances=1,
                misfire_grace_time=60,
                jitter=30,
            )
            scheduler.start()
            self._scheduler = scheduler
        except Exception:
            LOGGER.warning("mail_scheduler_unavailable")

    async def stop(self) -> None:
        if self._scheduler is not None:
            try:
                self._scheduler.shutdown(wait=False)
            except Exception:
                pass
            self._scheduler = None
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def start_connect(
        self, provider: str, payload: OutlookConnectRequest | ImapConnectRequest
    ) -> MailOperationOut:
        return self._start_operation(provider, "connect", lambda: self._connect(provider, payload))

    def start_sync(self, provider: str) -> MailOperationOut:
        with application_store.open_connection_tx(self.paths) as connection:
            account = store.get_account(connection, provider)
            if account is None or account["status"] == "disconnected":
                raise validation_error("Connect this mailbox before syncing.")
        return self._start_operation(provider, "sync", lambda: self._sync(provider))

    def _start_operation(
        self,
        provider: str,
        kind: str,
        action: Callable[[], Any],
    ) -> MailOperationOut:
        existing_id = self._provider_operation.get(provider)
        if existing_id is not None:
            existing = self._operations.get(existing_id)
            if existing is not None and existing.status in {"pending", "running"}:
                raise ApiError(409, "mail_operation_in_progress", "A mailbox operation is already running.")
        operation = _Operation(id=str(uuid4()), provider=provider, kind=kind)
        self._operations[operation.id] = operation
        self._provider_operation[provider] = operation.id
        task = asyncio.get_running_loop().create_task(self._run_operation(operation, action))
        self._tasks[operation.id] = task
        task.add_done_callback(lambda _task, op_id=operation.id: self._tasks.pop(op_id, None))
        self._trim_operations()
        return operation.public()

    async def _run_operation(self, operation: _Operation, action: Callable[[], Any]) -> None:
        operation.status = "running"
        try:
            await action()
        except asyncio.CancelledError:
            operation.status = "failed"
            operation.error_code = "operation_cancelled"
            raise
        except Exception as exc:
            error = self._safe_error(exc)
            operation.status = "failed"
            operation.error_code = error.code
            await self._record_failure(operation.provider, error)
            LOGGER.warning(
                "mail_operation_failed provider=%s kind=%s code=%s",
                operation.provider,
                operation.kind,
                error.code,
            )
        else:
            operation.status = "succeeded"
            self._failure_counts.pop(operation.provider, None)
        finally:
            if self._provider_operation.get(operation.provider) == operation.id:
                self._provider_operation.pop(operation.provider, None)

    def get_operation(self, operation_id: str) -> MailOperationOut:
        operation = self._operations.get(operation_id)
        if operation is None:
            raise ApiError(404, "mail_operation_not_found", "Mail operation not found.")
        return operation.public()

    def _trim_operations(self) -> None:
        if len(self._operations) <= 100:
            return
        finished = [
            op_id
            for op_id, operation in self._operations.items()
            if operation.status in {"succeeded", "failed"}
        ]
        for op_id in finished[: len(self._operations) - 100]:
            self._operations.pop(op_id, None)

    async def poll_connected_accounts(self) -> None:
        with application_store.open_connection_tx(self.paths) as connection:
            store.expire_pending_candidates(connection)
            rows = connection.execute(
                """
                SELECT provider FROM mail_accounts
                WHERE status = 'connected'
                   OR (status = 'error' AND (next_retry_at IS NULL OR next_retry_at <= ?))
                ORDER BY provider
                """,
                (now_iso(),),
            ).fetchall()
        for row in rows:
            try:
                self.start_sync(row["provider"])
            except ApiError:
                continue

    async def pause(self, provider: str) -> MailAccountOut:
        with application_store.open_connection_tx(self.paths) as connection:
            account = store.get_account(connection, provider)
            if account is None or account["status"] == "disconnected":
                raise validation_error("Connect this mailbox before pausing it.")
            row = store.update_account(connection, provider, status="paused", next_retry_at=None)
        return await self._account_out(row)

    async def resume(self, provider: str) -> MailAccountOut:
        with application_store.open_connection_tx(self.paths) as connection:
            account = store.get_account(connection, provider)
            if account is None or account["status"] != "paused":
                raise validation_error("Only a paused mailbox can be resumed.")
            row = store.update_account(
                connection,
                provider,
                status="connected",
                error_code=None,
                next_retry_at=None,
            )
        try:
            self.start_sync(provider)
        except ApiError:
            pass
        return await self._account_out(row)

    async def disconnect(self, provider: str) -> None:
        operation_id = self._provider_operation.get(provider)
        if operation_id is not None:
            operation = self._operations.get(operation_id)
            if operation is not None and operation.status in {"pending", "running"}:
                raise ApiError(
                    409,
                    "mail_operation_in_progress",
                    "Wait for the mailbox operation to finish before disconnecting.",
                )
        with application_store.open_connection_tx(self.paths) as connection:
            account = store.ensure_account(connection, provider)
        try:
            if provider == "outlook":
                await asyncio.to_thread(self._delete_outlook_cache)
            else:
                credential_store = self._credential_store_factory()
                refs = _unique_refs(
                    account.get("pending_credential_ref"),
                    account.get("previous_credential_ref"),
                    account.get("credential_ref"),
                )
                for credential_ref in refs:
                    await asyncio.to_thread(credential_store.delete, credential_ref)
        except CredentialStoreError as exc:
            error = self._safe_error(exc)
            raise ApiError(
                503,
                error.code,
                "The secure mailbox credential could not be deleted.",
            ) from None
        with application_store.open_connection_tx(self.paths) as connection:
            store.disconnect_account(connection, provider)

    async def masked_address(self, provider: str) -> str | None:
        connection = open_connection(self.paths)
        try:
            account = store.get_account(connection, provider)
        finally:
            connection.close()
        if account is None or account["status"] == "disconnected":
            return None
        try:
            if provider == "outlook":
                client_id = account.get("public_client_id")
                if not client_id:
                    return None
                auth = await asyncio.to_thread(self._outlook_auth_factory, client_id)
                username = await asyncio.to_thread(auth.account_username)
            else:
                credential_ref = account.get("credential_ref")
                if not credential_ref:
                    return None
                credential = await asyncio.to_thread(
                    self._credential_store_factory().read, credential_ref
                )
                username = credential.username
        except Exception:
            return None
        return _mask_mailbox(username)

    async def _cleanup_stale_imap_credentials(
        self, provider: str, *, fail_closed: bool = False
    ) -> None:
        connection = open_connection(self.paths)
        try:
            account = store.get_account(connection, provider)
        finally:
            connection.close()
        if account is None:
            return
        active_ref = account.get("credential_ref")
        refs = _unique_refs(
            account.get("pending_credential_ref"),
            account.get("previous_credential_ref"),
        )
        refs = [credential_ref for credential_ref in refs if credential_ref != active_ref]
        if refs:
            try:
                credential_store = self._credential_store_factory()
                for credential_ref in refs:
                    await asyncio.to_thread(credential_store.delete, credential_ref)
            except CredentialStoreError:
                LOGGER.warning("mail_stale_credential_cleanup_failed provider=%s", provider)
                if fail_closed:
                    raise
                return
        with application_store.open_connection_tx(self.paths) as connection:
            current = store.get_account(connection, provider)
            if current is None:
                return
            updates: dict[str, object] = {}
            if current.get("pending_credential_ref") in refs or (
                active_ref and current.get("pending_credential_ref") == active_ref
            ):
                updates["pending_credential_ref"] = None
            if current.get("previous_credential_ref") in refs or (
                active_ref and current.get("previous_credential_ref") == active_ref
            ):
                updates["previous_credential_ref"] = None
            if updates:
                store.update_account(connection, provider, status=current["status"], **updates)

    async def _account_out(self, row: dict) -> MailAccountOut:
        connection = open_connection(self.paths)
        try:
            count = int(
                connection.execute(
                    "SELECT count(*) FROM mail_event_candidates WHERE account_id = ? AND state = 'pending'",
                    (row["id"],),
                ).fetchone()[0]
            )
        finally:
            connection.close()
        return MailAccountOut(
            provider=row["provider"],
            status=row["status"],
            masked_address=await self.masked_address(row["provider"]),
            history_window=row.get("history_window") or "new_only",
            last_attempt_at=row.get("last_attempt_at"),
            last_success_at=row.get("last_success_at"),
            next_retry_at=row.get("next_retry_at"),
            error_code=row.get("last_error_code"),
            pending_count=count,
        )

    async def _connect(
        self, provider: str, payload: OutlookConnectRequest | ImapConnectRequest
    ) -> None:
        if provider in {"qq", "163"}:
            await self._cleanup_stale_imap_credentials(provider, fail_closed=True)
        elif provider == "outlook":
            await asyncio.to_thread(self._cleanup_outlook_staging_cache)
        with application_store.open_connection_tx(self.paths) as connection:
            previous = store.ensure_account(connection, provider)
            store.update_account(
                connection,
                provider,
                status="connecting",
                error_code=None,
                next_retry_at=None,
            )
        try:
            if provider == "outlook":
                if not isinstance(payload, OutlookConnectRequest):
                    raise validation_error("Outlook connect payload is invalid.")
                await self._connect_outlook(previous, payload)
            else:
                if not isinstance(payload, ImapConnectRequest):
                    raise validation_error("IMAP connect payload is invalid.")
                await self._connect_imap(previous, provider, payload)
        except (Exception, asyncio.CancelledError):
            with application_store.open_connection_tx(self.paths) as connection:
                current = store.get_account(connection, provider)
                if current is not None and current["status"] == "connecting":
                    restore_status = previous["status"]
                    if restore_status == "connecting":
                        restore_status = "error"
                    store.update_account(
                        connection,
                        provider,
                        status=restore_status,
                        error_code="connect_failed",
                    )
            raise

    async def _connect_outlook(self, account: dict, payload: OutlookConnectRequest) -> None:
        default_path = self._outlook_cache_path_factory()
        temp_path = default_path.with_name(f"msal.{uuid4().hex}.cache")
        backup_path = default_path.with_name(f"msal.{uuid4().hex}.backup")
        new_generation = str(uuid4())
        deferred_cleanup = False
        try:
            auth = await asyncio.to_thread(
                self._outlook_auth_factory,
                payload.client_id,
                cache_path=temp_path,
            )
            auth_task = asyncio.create_task(
                asyncio.to_thread(auth.acquire_interactive, timeout=300)
            )
            try:
                token = await asyncio.wait_for(asyncio.shield(auth_task), timeout=310)
            except (TimeoutError, asyncio.CancelledError):
                if not auth_task.done():
                    _defer_cache_cleanup(auth_task, temp_path)
                    deferred_cleanup = True
                raise
            username = await asyncio.to_thread(auth.account_username)
            if not username:
                raise MailServiceError("outlook_account_missing", auth_required=True)
            first_token = token

            def token_provider() -> str:
                nonlocal first_token
                if first_token:
                    current, first_token = first_token, ""
                    return current
                return auth.acquire_silent()

            result, extractions = await asyncio.to_thread(
                self._read_graph_round,
                token_provider,
                None,
                _history_since(payload.history_window),
            )
            if not temp_path.is_file():
                raise SecureStorageUnavailable("Encrypted Outlook cache was not created.")
            default_path.parent.mkdir(parents=True, exist_ok=True)
            had_previous_cache = default_path.is_file()
            if had_previous_cache:
                os.replace(default_path, backup_path)
            try:
                os.replace(temp_path, default_path)
                with application_store.open_connection_tx(self.paths) as connection:
                    connection.execute(
                        "DELETE FROM mail_sync_cursors WHERE account_id = ?", (account["id"],)
                    )
                    self._persist_extractions(
                        connection,
                        account,
                        "outlook",
                        extractions,
                        generation=new_generation,
                    )
                    store.save_graph_cursor(
                        connection,
                        account["id"],
                        result.delta_link,
                        _history_since(payload.history_window).isoformat(),
                    )
                    store.update_account(
                        connection,
                        "outlook",
                        status="connected",
                        history_window=payload.history_window,
                        public_client_id=payload.client_id,
                        error_code=None,
                        last_attempt=True,
                        last_success=True,
                        next_retry_at=None,
                        connection_generation=new_generation,
                    )
            except Exception:
                try:
                    _unlink_secure(default_path)
                    if had_previous_cache:
                        os.replace(backup_path, default_path)
                except (OSError, SecureStorageUnavailable) as exc:
                    raise SecureStorageUnavailable(
                        "Could not restore the previous encrypted Outlook cache."
                    ) from exc
                raise
            if had_previous_cache:
                # The transaction context commits while it exits.  Keep the
                # previous encrypted cache until that boundary has succeeded,
                # otherwise a commit failure would make rollback impossible.
                _unlink_secure(backup_path)
        finally:
            if not deferred_cleanup:
                _safe_unlink(temp_path)
                _safe_unlink(_lock_path(temp_path))

    async def _connect_imap(
        self,
        account: dict,
        provider: str,
        payload: ImapConnectRequest,
    ) -> None:
        since = _imap_initial_since(payload.history_window)
        result, extractions = await self._run_imap_round(
            provider,
            payload.mailbox_address,
            payload.authorization_code,
            None,
            since,
            None,
        )
        credential_store = self._credential_store_factory()
        new_ref = str(uuid4())
        old_ref = account.get("credential_ref")
        with application_store.open_connection_tx(self.paths) as connection:
            store.update_account(
                connection,
                provider,
                status="connecting",
                pending_credential_ref=new_ref,
            )
        try:
            await asyncio.to_thread(
                credential_store.write,
                new_ref,
                payload.mailbox_address,
                payload.authorization_code,
            )
            with application_store.open_connection_tx(self.paths) as connection:
                connection.execute(
                    "DELETE FROM mail_sync_cursors WHERE account_id = ?", (account["id"],)
                )
                self._persist_extractions(
                    connection,
                    account,
                    provider,
                    extractions,
                    generation=new_ref,
                )
                store.save_imap_cursor(
                    connection,
                    account["id"],
                    result.uidvalidity,
                    result.snapshot_uid,
                    since.isoformat() if since else None,
                )
                store.update_account(
                    connection,
                    provider,
                    status="connected",
                    history_window=payload.history_window,
                    error_code=None,
                    last_attempt=True,
                    last_success=True,
                    next_retry_at=None,
                    connection_generation=new_ref,
                    credential_ref=new_ref,
                    pending_credential_ref=None,
                    previous_credential_ref=old_ref,
                )
        except Exception:
            deleted = False
            try:
                await asyncio.to_thread(credential_store.delete, new_ref)
                deleted = True
            except CredentialStoreError:
                LOGGER.warning("mail_pending_credential_cleanup_failed provider=%s", provider)
            if deleted:
                with application_store.open_connection_tx(self.paths) as connection:
                    current = store.get_account(connection, provider)
                    if current is not None and current.get("pending_credential_ref") == new_ref:
                        store.update_account(
                            connection,
                            provider,
                            status=current["status"],
                            pending_credential_ref=None,
                        )
            raise
        if old_ref and old_ref != new_ref:
            try:
                await asyncio.to_thread(credential_store.delete, old_ref)
            except CredentialStoreError:
                LOGGER.warning("mail_previous_credential_cleanup_failed provider=%s", provider)
            else:
                with application_store.open_connection_tx(self.paths) as connection:
                    current = store.get_account(connection, provider)
                    if current is not None and current.get("previous_credential_ref") == old_ref:
                        store.update_account(
                            connection,
                            provider,
                            status=current["status"],
                            previous_credential_ref=None,
                        )

    async def _sync(self, provider: str) -> None:
        with application_store.open_connection_tx(self.paths) as connection:
            account = store.get_account(connection, provider)
            if account is None or account["status"] == "disconnected":
                raise validation_error("Connect this mailbox before syncing.")
            original_status = account["status"]
            store.update_account(connection, provider, status=original_status, last_attempt=True)
            cursor = store.get_cursor(connection, account["id"])
        if provider == "outlook":
            await self._sync_outlook(account, cursor)
        else:
            await self._sync_imap(account, cursor)
        with application_store.open_connection_tx(self.paths) as connection:
            current = store.get_account(connection, provider)
            final_status = (
                "paused"
                if original_status == "paused"
                or (current is not None and current["status"] == "paused")
                else "connected"
            )
            store.update_account(
                connection,
                provider,
                status=final_status,
                error_code=None,
                last_success=True,
                next_retry_at=None,
            )

    async def _sync_outlook(self, account: dict, cursor: dict | None) -> None:
        client_id = account.get("public_client_id")
        if not client_id:
            raise MailServiceError("outlook_client_id_missing", auth_required=True)
        auth = await asyncio.to_thread(self._outlook_auth_factory, client_id)
        delta_link = cursor.get("graph_delta_link") if cursor else None
        since = None if delta_link else _history_since(account["history_window"])
        try:
            result, extractions = await asyncio.to_thread(
                self._read_graph_round, auth.acquire_silent, delta_link, since
            )
        except GraphCursorExpired:
            since = _overlap_since(account.get("last_success_at"))
            result, extractions = await asyncio.to_thread(
                self._read_graph_round, auth.acquire_silent, None, since
            )
        with application_store.open_connection_tx(self.paths) as connection:
            self._persist_extractions(connection, account, "outlook", extractions)
            store.save_graph_cursor(
                connection,
                account["id"],
                result.delta_link,
                since.isoformat() if since else (cursor or {}).get("initial_cutoff_at"),
            )

    def _read_graph_round(
        self,
        token_provider: Callable[[], str],
        delta_link: str | None,
        since: datetime | None,
    ) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
        extractions: list[tuple[str, dict[str, Any]]] = []
        with self._graph_client_factory(token_provider) as client:
            result = client.fetch_delta(delta_link=delta_link, since=since)
            for header in result.messages:
                sender = " ".join(
                    item for item in (header.sender_name, header.sender_address) if item
                )
                if not is_likely_recruitment_header(header.subject, sender):
                    continue
                extra_reasons: list[str] = []
                try:
                    body = client.fetch_unique_body(header.message_id).text
                except GraphPayloadTooLarge:
                    body = ""
                    extra_reasons.append("body_too_large")
                except (GraphMessageUnavailable, GraphProtocolError):
                    body = ""
                    extra_reasons.append("body_missing")
                extracted = classify_and_extract(
                    subject=header.subject,
                    sender=sender,
                    received_at=header.received_at,
                    body=body,
                )
                if extracted.negative_signal:
                    continue
                mapping = _extraction_mapping(extracted, extra_reasons)
                extractions.append((header.message_id, mapping))
                del body, extracted
        return result, extractions

    async def _sync_imap(self, account: dict, cursor: dict | None) -> None:
        credential_ref = account.get("credential_ref")
        if not credential_ref:
            raise MailServiceError("imap_credential_missing", auth_required=True)
        try:
            credential = await asyncio.to_thread(
                self._credential_store_factory().read, credential_ref
            )
        except CredentialNotFound as exc:
            raise MailServiceError("imap_credential_missing", auth_required=True) from exc
        imap_cursor = None
        if cursor and cursor.get("imap_uidvalidity") is not None:
            imap_cursor = ImapCursor(
                uidvalidity=int(cursor["imap_uidvalidity"]),
                last_uid=int(cursor.get("imap_last_uid") or 0),
            )
        since = None if imap_cursor else _imap_initial_since(account["history_window"])
        reset_since = _overlap_since(account.get("last_success_at")) if imap_cursor else None
        result, extractions = await self._run_imap_round(
            account["provider"],
            credential.username,
            credential.secret,
            imap_cursor,
            since,
            reset_since,
        )
        with application_store.open_connection_tx(self.paths) as connection:
            self._persist_extractions(connection, account, account["provider"], extractions)
            store.save_imap_cursor(
                connection,
                account["id"],
                result.uidvalidity,
                result.snapshot_uid,
                since.isoformat() if since else (cursor or {}).get("initial_cutoff_at"),
            )

    def _read_imap_round(
        self,
        provider: str,
        username: str,
        secret: str,
        cursor: ImapCursor | None,
        since: datetime | None,
        reset_since: datetime | None,
        cancel_event: Any | None = None,
    ) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
        extractions: list[tuple[str, dict[str, Any]]] = []
        with self._imap_connector_factory(provider, username, secret) as connector:
            result = connector.scan_headers(
                cursor,
                since=since,
                reset_since=reset_since,
                cancel_event=cancel_event,
            )
            for message in result.messages:
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError
                received_at = message.internal_date or message.header.sent_at
                if received_at is None:
                    continue
                if not is_likely_recruitment_header(
                    message.header.subject, message.header.sender
                ):
                    continue
                extra_reasons: list[str] = []
                charset_fallback = False
                quoted_only = False
                quoted_tail_trimmed = False
                try:
                    fetched = connector.fetch_body(message.uid)
                    body = fetched.text if fetched is not None else ""
                    charset_fallback = bool(
                        fetched is not None and fetched.used_charset_fallback
                    )
                    quoted_only = bool(fetched is not None and fetched.quoted_only)
                    quoted_tail_trimmed = bool(
                        fetched is not None and fetched.quoted_tail_trimmed
                    )
                    if fetched is None:
                        extra_reasons.append("body_missing")
                except ImapConnectorError as exc:
                    code = str(exc)
                    if code.startswith("mail_") or code == "imap_body_missing":
                        body = ""
                        extra_reasons.append(
                            "body_too_large" if "too_large" in code else "body_missing"
                        )
                    else:
                        raise
                extracted = classify_and_extract(
                    subject=message.header.subject,
                    sender=message.header.sender,
                    received_at=received_at,
                    body=body,
                    charset_fallback=charset_fallback,
                    quoted_only=quoted_only,
                    quoted_tail_trimmed=quoted_tail_trimmed,
                )
                if extracted.negative_signal:
                    continue
                mapping = _extraction_mapping(extracted, extra_reasons)
                extractions.append(
                    (f"{result.uidvalidity}:{message.uid}", mapping)
                )
                del body, extracted
        return result, extractions

    async def _run_imap_round(
        self,
        provider: str,
        username: str,
        secret: str,
        cursor: ImapCursor | None,
        since: datetime | None,
        reset_since: datetime | None,
    ) -> tuple[Any, list[tuple[str, dict[str, Any]]]]:
        from threading import Event

        cancel_event = Event()
        task = asyncio.create_task(
            asyncio.to_thread(
                self._read_imap_round,
                provider,
                username,
                secret,
                cursor,
                since,
                reset_since,
                cancel_event,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel_event.set()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
            raise

    @staticmethod
    def _persist_extractions(
        connection,
        account: dict,
        provider: str,
        extractions: list[tuple[str, dict[str, Any]]],
        *,
        generation: str | None = None,
    ) -> None:
        namespace = generation or account.get("connection_generation") or account["id"]
        for source_key, extracted in extractions:
            store.create_candidate(
                connection,
                account_id=account["id"],
                provider=provider,
                source_key=f"{namespace}:{source_key}",
                extracted=extracted,
            )

    async def _record_failure(self, provider: str, error: MailServiceError) -> None:
        count = self._failure_counts.get(provider, 0) + 1
        self._failure_counts[provider] = count
        if error.retry_after is not None:
            next_retry = datetime.now(CN_TZ) + timedelta(seconds=max(0, error.retry_after))
        else:
            minutes = BACKOFF_MINUTES[min(count - 1, len(BACKOFF_MINUTES) - 1)]
            next_retry = datetime.now(CN_TZ) + timedelta(minutes=minutes)
        with application_store.open_connection_tx(self.paths) as connection:
            account = store.get_account(connection, provider)
            if account is None or account["status"] == "disconnected":
                return
            if account["status"] == "paused":
                status = "paused"
                retry_value = None
            else:
                status = "needs_reauth" if error.auth_required else "error"
                retry_value = None if error.auth_required else next_retry.isoformat(timespec="milliseconds")
            store.update_account(
                connection,
                provider,
                status=status,
                error_code=error.code,
                next_retry_at=retry_value,
            )

    @staticmethod
    def _safe_error(exc: Exception) -> MailServiceError:
        if isinstance(exc, MailServiceError):
            return exc
        if isinstance(exc, GraphAuthenticationRequired):
            return MailServiceError("outlook_reauth_required", auth_required=True)
        if isinstance(exc, GraphThrottled):
            return MailServiceError("outlook_rate_limited", retry_after=exc.retry_after)
        if isinstance(exc, GraphCursorExpired):
            return MailServiceError("outlook_cursor_expired")
        if isinstance(exc, GraphPayloadTooLarge):
            return MailServiceError("outlook_backfill_limit")
        if isinstance(exc, GraphTransientError):
            return MailServiceError("outlook_network_error")
        if isinstance(exc, GraphProtocolError):
            return MailServiceError("outlook_protocol_error")
        if isinstance(exc, GraphError):
            return MailServiceError("outlook_request_failed")
        if isinstance(exc, CredentialNotFound):
            return MailServiceError("credential_missing", auth_required=True)
        if isinstance(exc, SecureStorageUnavailable):
            return MailServiceError("credential_store_unavailable")
        if isinstance(exc, CredentialStoreError):
            return MailServiceError("credential_store_error")
        if isinstance(exc, ImapConnectorError):
            code = str(exc)
            if code == "imap_auth_or_connection_failed":
                return MailServiceError("imap_auth_or_connection_failed")
            return MailServiceError(code if code.startswith(("imap_", "mail_")) else "imap_error")
        if isinstance(exc, TimeoutError):
            return MailServiceError("mail_operation_timeout")
        if isinstance(exc, ApiError):
            return MailServiceError(exc.code)
        return MailServiceError("mail_operation_failed")

    def _cleanup_outlook_staging_cache(self) -> None:
        path = self._outlook_cache_path_factory()
        try:
            siblings = list(path.parent.iterdir()) if path.parent.is_dir() else []
        except OSError as exc:
            raise SecureStorageUnavailable(
                "Could not inspect encrypted Outlook cache files."
            ) from exc
        for sibling in siblings:
            if OUTLOOK_STAGING_CACHE_RE.fullmatch(sibling.name):
                _unlink_secure(sibling)

    def _delete_outlook_cache(self) -> None:
        path = self._outlook_cache_path_factory()
        self._cleanup_outlook_staging_cache()
        # Keep the active cache until every known orphan has been removed.  If
        # any deletion fails, disconnect remains uncommitted and the currently
        # connected account can still authenticate.
        _unlink_secure(_lock_path(path))
        _unlink_secure(path)


def _extraction_mapping(extracted: Any, extra_reasons: list[str]) -> dict[str, Any]:
    return {
        "proposed_stage": extracted.stage,
        "event_date": extracted.event_date,
        "scheduled_date": extracted.scheduled_date,
        "scheduled_time": extracted.scheduled_time,
        "deadline_date": extracted.deadline_date,
        "deadline_time": extracted.deadline_time,
        "timezone": extracted.timezone,
        "company_name": extracted.company_name,
        "job_title": extracted.job_title,
        "job_code": extracted.job_code,
        "job_url": extracted.job_url,
        "location": extracted.location,
        "review_reasons": [*extracted.reasons, *extra_reasons],
    }


def _history_since(window: HistoryWindow | str, *, now: datetime | None = None) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    days = {"new_only": 0, "last_30_days": 30, "last_90_days": 90}.get(str(window), 0)
    return current - timedelta(days=days)


def _imap_initial_since(window: HistoryWindow | str) -> datetime | None:
    return None if window == "new_only" else _history_since(window)


def _overlap_since(
    last_success_at: str | None, *, now: datetime | None = None
) -> datetime:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    earliest = current - timedelta(days=MAX_CURSOR_REBUILD_DAYS)
    if last_success_at:
        try:
            parsed = datetime.fromisoformat(last_success_at.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                overlap = parsed.astimezone(UTC) - timedelta(hours=24)
                return min(current, max(overlap, earliest))
        except ValueError:
            pass
    return current - timedelta(hours=24)


def _mask_mailbox(value: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    local, domain = value.rsplit("@", 1)
    if not local or not domain:
        return None
    visible = local[0]
    return f"{visible}{'*' * max(3, len(local) - 1)}@{domain}"


def _unique_refs(*values: object) -> list[str]:
    result: list[str] = []
    for value in values:
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def _lock_path(path: Path) -> Path:
    return Path(f"{path}.lockfile")


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _unlink_secure(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise SecureStorageUnavailable("Could not delete an encrypted Outlook cache.") from exc


def _defer_cache_cleanup(task: asyncio.Task[Any], path: Path) -> None:
    def cleanup(_task: asyncio.Task[Any]) -> None:
        try:
            _task.exception()
        except (asyncio.CancelledError, Exception):
            pass
        _safe_unlink(path)
        _safe_unlink(_lock_path(path))

    task.add_done_callback(cleanup)


__all__ = ["MailService", "MailServiceError"]
