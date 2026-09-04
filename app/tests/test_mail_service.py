"""Mailbox orchestration tests with deterministic provider doubles."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta

import pytest

from backend import store as application_store
from backend.database import open_connection
from backend.errors import ApiError
from backend.mail import store as mail_store
from backend.mail.credentials import (
    CredentialNotFound,
    SecureStorageUnavailable,
    StoredCredential,
)
from backend.mail.imap import (
    ImapConnectorError,
    ImapFetchedBody,
    ImapMessageHeader,
    ImapScanResult,
)
from backend.mail.parsing import ParsedHeader
from backend.mail.schemas import ImapConnectRequest
from backend.mail.service import MailService, _overlap_since
from backend.schemas import CreateApplication


class MemoryCredentialStore:
    def __init__(self) -> None:
        self.values: dict[str, StoredCredential] = {}

    def write(self, account_id: str, username: str, secret: str) -> None:
        self.values[account_id] = StoredCredential(username=username, secret=secret)

    def read(self, account_id: str) -> StoredCredential:
        try:
            return self.values[account_id]
        except KeyError as exc:
            raise CredentialNotFound("missing") from exc

    def delete(self, account_id: str, *, missing_ok: bool = True) -> None:
        if account_id not in self.values and not missing_ok:
            raise CredentialNotFound("missing")
        self.values.pop(account_id, None)


class FailOnceDeleteCredentialStore(MemoryCredentialStore):
    def __init__(self) -> None:
        super().__init__()
        self.fail_once_for: set[str] = set()

    def delete(self, account_id: str, *, missing_ok: bool = True) -> None:
        if account_id in self.fail_once_for:
            self.fail_once_for.remove(account_id)
            raise SecureStorageUnavailable("synthetic delete failure")
        super().delete(account_id, missing_ok=missing_ok)


class ImapScenario:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.deliver_message = False
        self.deliver_on_initial = False
        self.quoted_only = False

    def __call__(self, provider: str, username: str, secret: str):
        scenario = self

        class Connector:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def scan_headers(self, cursor, *, since=None, reset_since=None, cancel_event=None):
                scenario.calls.append(
                    {
                        "provider": provider,
                        "username": username,
                        "secret": secret,
                        "cursor": cursor,
                        "since": since,
                        "reset_since": reset_since,
                    }
                )
                initial_backfill = cursor is None and since is not None
                if not scenario.deliver_message or (
                    cursor is None and not (scenario.deliver_on_initial and initial_backfill)
                ):
                    return ImapScanResult((), (), 7001, 40, False)
                header = ImapMessageHeader(
                    uid=41,
                    internal_date=datetime(2026, 8, 30, 2, 0, tzinfo=UTC),
                    message_size=1024,
                    header=ParsedHeader(
                        subject="第一轮面试邀请",
                        sender="recruiting@test",
                        message_id="<fixture-41@test>",
                        sent_at=None,
                    ),
                )
                return ImapScanResult((header,), (), 7001, 41, False)

            def fetch_body(self, uid: int):
                assert uid == 41
                return ImapFetchedBody(
                    uid=uid,
                    text=(
                        "公司：示例云科技\n"
                        "岗位：数据工程师\n"
                        "工作地点：上海\n"
                        "面试时间：2026年9月3日 上午10点30\n"
                        "RAW-MAIL-BODY-MARKER"
                    ),
                    content_type="text/plain",
                    charset="utf-8",
                    used_charset_fallback=False,
                    quoted_tail_trimmed=False,
                    quoted_only=scenario.quoted_only,
                )

        return Connector()


async def _finish(service: MailService, operation_id: str):
    while service.get_operation(operation_id).status in {"pending", "running"}:
        await asyncio.sleep(0)
    return service.get_operation(operation_id)


def test_scheduler_poll_expires_candidates_without_ui_access(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        mail_store.ensure_account(connection, "qq")
        candidate, _, _ = mail_store.create_candidate(
            connection,
            provider="qq",
            source_key="expired-scheduler-fixture",
            extracted={
                "proposed_stage": "offer",
                "event_date": "2026-01-01",
                "company_name": "示例公司",
                "job_title": "示例岗位",
            },
        )
        assert candidate is not None
        connection.execute(
            "UPDATE mail_event_candidates SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+08:00", candidate.id),
        )

    service = MailService(client.app.state.paths, scheduler_enabled=False)
    asyncio.run(service.poll_connected_accounts())

    connection = open_connection(client.app.state.paths)
    try:
        row = connection.execute(
            "SELECT * FROM mail_event_candidates WHERE id = ?", (candidate.id,)
        ).fetchone()
    finally:
        connection.close()
    assert row["state"] == "expired"
    assert row["company_name"] is None
    assert row["job_title"] is None
    assert row["event_date"] is None


def test_imap_initial_snapshot_then_incremental_commit_without_secret_persistence(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        application_store.create_application(
            connection,
            CreateApplication(
                company_name="示例云科技",
                job_title="数据工程师",
                location="上海",
                event_date="2026-08-01",
            ),
        )

    vault = MemoryCredentialStore()
    scenario = ImapScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        credential_store_factory=lambda: vault,
        imap_connector_factory=scenario,
    )

    async def run() -> None:
        connect = service.start_connect(
            "qq",
            ImapConnectRequest(
                mailbox_address="fixture-user@qq",
                authorization_code="fixture-secret-code",
                history_window="new_only",
            ),
        )
        assert (await _finish(service, connect.id)).status == "succeeded"
        scenario.deliver_message = True
        sync = service.start_sync("qq")
        assert (await _finish(service, sync.id)).status == "succeeded"
        await service.stop()

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        account = connection.execute(
            "SELECT * FROM mail_accounts WHERE provider = 'qq'"
        ).fetchone()
        cursor = connection.execute(
            "SELECT * FROM mail_sync_cursors WHERE account_id = ?", (account["id"],)
        ).fetchone()
        event = connection.execute(
            "SELECT * FROM application_events WHERE source = 'email_extract'"
        ).fetchone()
        candidate = connection.execute("SELECT * FROM mail_event_candidates").fetchone()
        dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert account["status"] == "connected"
    assert cursor["imap_uidvalidity"] == 7001
    assert cursor["imap_last_uid"] == 41
    assert scenario.calls[0]["cursor"] is None
    assert scenario.calls[0]["since"] is None
    assert scenario.calls[1]["cursor"].last_uid == 40
    assert event["stage"] == "interview_1"
    assert event["scheduled_date"] == "2026-09-03"
    assert event["scheduled_time"] == "10:30"
    assert candidate["state"] == "committed"
    assert candidate["company_name"] is None
    assert account["credential_ref"] != account["id"]
    assert vault.values[account["credential_ref"]].secret == "fixture-secret-code"
    assert "fixture-secret-code" not in dump
    assert "fixture-user@qq" not in dump
    assert "RAW-MAIL-BODY-MARKER" not in dump


def test_cursor_is_not_advanced_when_structured_persistence_fails(client, monkeypatch) -> None:
    vault = MemoryCredentialStore()
    scenario = ImapScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        credential_store_factory=lambda: vault,
        imap_connector_factory=scenario,
    )

    async def connect() -> None:
        operation = service.start_connect(
            "163",
            ImapConnectRequest(
                mailbox_address="fixture-user@163",
                authorization_code="fixture-secret-code",
            ),
        )
        assert (await _finish(service, operation.id)).status == "succeeded"

    asyncio.run(connect())
    scenario.deliver_message = True

    from backend.mail import service as service_module

    def fail_persistence(*_args, **_kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(service_module.store, "create_candidate", fail_persistence)

    async def sync() -> None:
        operation = service.start_sync("163")
        result = await _finish(service, operation.id)
        assert result.status == "failed"
        assert result.error_code == "mail_operation_failed"
        await service.stop()

    asyncio.run(sync())

    connection = open_connection(client.app.state.paths)
    try:
        account = connection.execute(
            "SELECT * FROM mail_accounts WHERE provider = '163'"
        ).fetchone()
        cursor = connection.execute(
            "SELECT * FROM mail_sync_cursors WHERE account_id = ?", (account["id"],)
        ).fetchone()
    finally:
        connection.close()
    assert cursor["imap_last_uid"] == 40
    assert account["last_error_code"] == "mail_operation_failed"


def test_quote_only_imap_message_never_auto_advances_matching_application(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        application = application_store.create_application(
            connection,
            CreateApplication(
                company_name="示例云科技",
                job_title="数据工程师",
                location="上海",
                event_date="2026-08-01",
            ),
        )

    vault = MemoryCredentialStore()
    scenario = ImapScenario()
    scenario.quoted_only = True
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        credential_store_factory=lambda: vault,
        imap_connector_factory=scenario,
    )

    async def run() -> None:
        connect = service.start_connect(
            "qq",
            ImapConnectRequest(
                mailbox_address="fixture-user@qq",
                authorization_code="fixture-secret-code",
            ),
        )
        assert (await _finish(service, connect.id)).status == "succeeded"
        scenario.deliver_message = True
        sync = service.start_sync("qq")
        assert (await _finish(service, sync.id)).status == "succeeded"
        await service.stop()

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        record = connection.execute(
            "SELECT current_status FROM applications WHERE id = ?", (application.id,)
        ).fetchone()
        candidate = connection.execute(
            "SELECT state, review_reasons FROM mail_event_candidates"
        ).fetchone()
        event_count = connection.execute(
            "SELECT count(*) FROM application_events WHERE source = 'email_extract'"
        ).fetchone()[0]
    finally:
        connection.close()
    assert record["current_status"] == "pending_review"
    assert candidate["state"] == "pending"
    assert "quoted_only_signal" in candidate["review_reasons"]
    assert event_count == 0


def test_imap_sync_passes_last_success_overlap_for_uidvalidity_reset(client) -> None:
    vault = MemoryCredentialStore()
    scenario = ImapScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        credential_store_factory=lambda: vault,
        imap_connector_factory=scenario,
    )
    last_success = datetime.now(UTC) - timedelta(days=10)

    async def run() -> None:
        connect = service.start_connect(
            "163",
            ImapConnectRequest(
                mailbox_address="fixture-user@163",
                authorization_code="fixture-secret-code",
            ),
        )
        assert (await _finish(service, connect.id)).status == "succeeded"
        with application_store.open_connection_tx(client.app.state.paths) as connection:
            connection.execute(
                "UPDATE mail_accounts SET last_success_at = ? WHERE provider = '163'",
                (last_success.isoformat(),),
            )
        sync = service.start_sync("163")
        assert (await _finish(service, sync.id)).status == "succeeded"
        await service.stop()

    asyncio.run(run())
    assert scenario.calls[1]["reset_since"] == last_success - timedelta(hours=24)


def test_cursor_reset_overlap_is_capped_after_long_inactivity() -> None:
    current = datetime(2026, 8, 30, 6, tzinfo=UTC)
    stale_success = datetime(2024, 1, 1, 6, tzinfo=UTC)

    assert _overlap_since(stale_success.isoformat(), now=current) == (
        current - timedelta(days=90)
    )


def test_reconnect_rotates_fingerprint_namespace_and_deletes_old_credential(client) -> None:
    vault = MemoryCredentialStore()
    scenario = ImapScenario()
    scenario.deliver_message = True
    scenario.deliver_on_initial = True
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        credential_store_factory=lambda: vault,
        imap_connector_factory=scenario,
    )

    async def connect(address: str, secret: str) -> None:
        operation = service.start_connect(
            "qq",
            ImapConnectRequest(
                mailbox_address=address,
                authorization_code=secret,
                history_window="last_30_days",
            ),
        )
        assert (await _finish(service, operation.id)).status == "succeeded"

    async def run() -> tuple[str, str]:
        await connect("first@qq", "first-code")
        connection = open_connection(client.app.state.paths)
        try:
            first = dict(
                connection.execute(
                    "SELECT * FROM mail_accounts WHERE provider = 'qq'"
                ).fetchone()
            )
        finally:
            connection.close()
        await connect("second@qq", "second-code")
        await service.stop()
        return first["credential_ref"], first["connection_generation"]

    old_ref, old_generation = asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        current = dict(
            connection.execute(
                "SELECT * FROM mail_accounts WHERE provider = 'qq'"
            ).fetchone()
        )
        fingerprints = [
            row[0]
            for row in connection.execute(
                "SELECT fingerprint FROM mail_event_candidates ORDER BY id"
            ).fetchall()
        ]
    finally:
        connection.close()
    assert len(fingerprints) == 2
    assert len(set(fingerprints)) == 2
    assert current["connection_generation"] != old_generation
    assert current["credential_ref"] == current["connection_generation"]
    assert current["previous_credential_ref"] is None
    assert old_ref not in vault.values
    assert list(vault.values) == [current["credential_ref"]]
    assert vault.values[current["credential_ref"]].username == "second@qq"


def test_startup_retries_deferred_previous_credential_cleanup(client) -> None:
    vault = FailOnceDeleteCredentialStore()
    scenario = ImapScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        credential_store_factory=lambda: vault,
        imap_connector_factory=scenario,
    )

    async def connect(address: str, secret: str) -> None:
        operation = service.start_connect(
            "qq",
            ImapConnectRequest(
                mailbox_address=address,
                authorization_code=secret,
            ),
        )
        assert (await _finish(service, operation.id)).status == "succeeded"

    async def run() -> tuple[str, str]:
        await connect("first@qq", "first-code")
        connection = open_connection(client.app.state.paths)
        try:
            old_ref = mail_store.get_account(connection, "qq")["credential_ref"]
        finally:
            connection.close()
        vault.fail_once_for.add(old_ref)
        await connect("second@qq", "second-code")

        connection = open_connection(client.app.state.paths)
        try:
            before_cleanup = mail_store.get_account(connection, "qq")
        finally:
            connection.close()
        assert before_cleanup["previous_credential_ref"] == old_ref
        assert old_ref in vault.values

        await service.start()
        await service.stop()
        return old_ref, before_cleanup["credential_ref"]

    old_ref, active_ref = asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        account = mail_store.get_account(connection, "qq")
    finally:
        connection.close()
    assert account["credential_ref"] == active_ref
    assert account["previous_credential_ref"] is None
    assert old_ref not in vault.values
    assert list(vault.values) == [active_ref]


def test_reconnect_refuses_to_overwrite_unremoved_credential_reference(client) -> None:
    vault = FailOnceDeleteCredentialStore()
    scenario = ImapScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        credential_store_factory=lambda: vault,
        imap_connector_factory=scenario,
    )

    async def connect(address: str, secret: str):
        operation = service.start_connect(
            "qq",
            ImapConnectRequest(
                mailbox_address=address,
                authorization_code=secret,
            ),
        )
        return await _finish(service, operation.id)

    async def run() -> tuple[str, str]:
        assert (await connect("first@qq", "first-code")).status == "succeeded"
        connection = open_connection(client.app.state.paths)
        try:
            first_ref = mail_store.get_account(connection, "qq")["credential_ref"]
        finally:
            connection.close()

        vault.fail_once_for.add(first_ref)
        assert (await connect("second@qq", "second-code")).status == "succeeded"
        connection = open_connection(client.app.state.paths)
        try:
            second = mail_store.get_account(connection, "qq")
        finally:
            connection.close()
        assert second["previous_credential_ref"] == first_ref

        vault.fail_once_for.add(first_ref)
        failed = await connect("third@qq", "third-code")
        assert failed.status == "failed"
        assert failed.error_code == "credential_store_unavailable"
        await service.stop()
        return first_ref, second["credential_ref"]

    first_ref, active_ref = asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        account = mail_store.get_account(connection, "qq")
    finally:
        connection.close()
    assert account["credential_ref"] == active_ref
    assert account["previous_credential_ref"] == first_ref
    assert set(vault.values) == {first_ref, active_ref}


class CooperativeCancellationScenario:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.stopped = threading.Event()

    def __call__(self, _provider: str, _username: str, _secret: str):
        scenario = self

        class Connector:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def scan_headers(self, _cursor, *, since=None, reset_since=None, cancel_event=None):
                del since, reset_since
                scenario.started.set()
                assert cancel_event is not None
                assert cancel_event.wait(2)
                scenario.stopped.set()
                raise ImapConnectorError("imap_operation_cancelled")

        return Connector()


def test_imap_worker_cooperatively_stops_before_async_cancellation_returns(client) -> None:
    scenario = CooperativeCancellationScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        imap_connector_factory=scenario,
    )

    async def run() -> None:
        task = asyncio.create_task(
            service._run_imap_round("qq", "person@qq", "code", None, None, None)
        )
        assert await asyncio.to_thread(scenario.started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert scenario.stopped.is_set()
