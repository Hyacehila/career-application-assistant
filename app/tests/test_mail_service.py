"""Mailbox orchestration tests with deterministic provider doubles."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
from backend.mail.graph import (
    GraphDeltaResult,
    GraphMailClient,
    GraphMailHeader,
    GraphMessageUnavailable,
    GraphProtocolError,
)
from backend.mail.imap import (
    ImapConnectorError,
    ImapFetchedBody,
    ImapMessageHeader,
    ImapScanResult,
)
from backend.mail.parsing import ParsedHeader
from backend.mail.schemas import ImapConnectRequest, OutlookConnectRequest
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
        account = mail_store.ensure_account(connection, "qq")
        candidate, _, _ = mail_store.create_candidate(
            connection,
            account_id=account["id"],
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


class GraphScenario:
    def __init__(self) -> None:
        self.calls: list[tuple[str | None, datetime | None]] = []

    def client(self, _token_provider):
        scenario = self

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def fetch_delta(self, *, delta_link=None, since=None):
                scenario.calls.append((delta_link, since))
                sequence = len(scenario.calls)
                return GraphDeltaResult(
                    (),
                    f"https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken={sequence}",
                )

        return Client()


class FakeOutlookAuth:
    def __init__(self, client_id: str, *, cache_path: Path | None = None) -> None:
        self.client_id = client_id
        self.cache_path = cache_path

    def acquire_interactive(self, *, timeout: int = 300) -> str:
        assert timeout == 300
        assert self.cache_path is not None
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_bytes(b"dpapi-fixture-cache")
        return "fixture-access-token"

    def acquire_silent(self) -> str:
        return "fixture-refreshed-token"

    def account_username(self) -> str:
        return "fixture-user@outlook"


def test_outlook_connect_commits_encrypted_cache_and_delta_cursor(client, tmp_path, monkeypatch) -> None:
    cache_path = tmp_path / "secure" / "msal.cache"
    from backend.mail import service as service_module

    monkeypatch.setattr(service_module, "default_msal_cache_path", lambda: cache_path)
    graph = GraphScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_auth_factory=FakeOutlookAuth,
        graph_client_factory=graph.client,
    )

    async def run() -> None:
        connect = service.start_connect(
            "outlook",
            OutlookConnectRequest(
                client_id="00000000-0000-0000-0000-000000000001",
                history_window="new_only",
            ),
        )
        assert (await _finish(service, connect.id)).status == "succeeded"
        sync = service.start_sync("outlook")
        assert (await _finish(service, sync.id)).status == "succeeded"
        await service.stop()

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        account = connection.execute(
            "SELECT * FROM mail_accounts WHERE provider = 'outlook'"
        ).fetchone()
        cursor = connection.execute(
            "SELECT * FROM mail_sync_cursors WHERE account_id = ?", (account["id"],)
        ).fetchone()
        dump = "\n".join(connection.iterdump())
    finally:
        connection.close()
    assert account["status"] == "connected"
    assert cursor["graph_delta_link"].endswith("$deltatoken=2")
    assert graph.calls[0][0] is None and graph.calls[0][1] is not None
    assert graph.calls[1][0].endswith("$deltatoken=1") and graph.calls[1][1] is None
    assert cache_path.read_bytes() == b"dpapi-fixture-cache"
    assert "fixture-access-token" not in dump
    assert "fixture-refreshed-token" not in dump
    assert "fixture-user@outlook" not in dump


OLD_CLIENT_ID = "00000000-0000-0000-0000-000000000010"
NEW_CLIENT_ID = "00000000-0000-0000-0000-000000000011"
OLD_DELTA_LINK = (
    "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
    "$deltatoken=old-fixture"
)
NEW_DELTA_LINK = (
    "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
    "$deltatoken=new-fixture"
)


def _connected_outlook(paths) -> tuple[dict, str]:
    with application_store.open_connection_tx(paths) as connection:
        account = mail_store.ensure_account(connection, "outlook")
        original_generation = account["connection_generation"]
        account = mail_store.update_account(
            connection,
            "outlook",
            status="connected",
            public_client_id=OLD_CLIENT_ID,
        )
        mail_store.save_graph_cursor(
            connection,
            account["id"],
            OLD_DELTA_LINK,
            "2026-08-01T00:00:00+00:00",
        )
    return account, original_generation


class _SilentAuth:
    def __init__(self) -> None:
        self.calls = 0

    def acquire_silent(self) -> str:
        self.calls += 1
        return f"fixture-token-{self.calls}"


class _BodyErrorGraph:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.body_calls = 0

    def client(self, token_provider):
        scenario = self

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def fetch_delta(self, *, delta_link=None, since=None):
                assert delta_link == OLD_DELTA_LINK
                assert since is None
                token_provider()
                return GraphDeltaResult(
                    (
                        GraphMailHeader(
                            message_id="immutable-body-error",
                            internet_message_id=None,
                            subject="第一轮面试邀请：2026年9月3日 10:00",
                            sender_name="示例招聘团队",
                            sender_address="recruiting@test",
                            received_at=datetime(2026, 8, 30, 2, 0, tzinfo=UTC),
                        ),
                    ),
                    NEW_DELTA_LINK,
                )

            def fetch_unique_body(self, message_id: str):
                assert message_id == "immutable-body-error"
                scenario.body_calls += 1
                token_provider()
                raise scenario.error

        return Client()


@pytest.mark.parametrize(
    "body_error",
    [
        GraphMessageUnavailable("fixture-message-gone"),
        GraphProtocolError("fixture-body-invalid"),
    ],
    ids=["message-404", "body-protocol-error"],
)
def test_outlook_body_error_does_not_block_delta_cursor(client, body_error) -> None:
    _connected_outlook(client.app.state.paths)
    auth = _SilentAuth()
    graph = _BodyErrorGraph(body_error)
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_auth_factory=lambda _client_id: auth,
        graph_client_factory=graph.client,
    )

    async def run() -> None:
        operation = service.start_sync("outlook")
        assert (await _finish(service, operation.id)).status == "succeeded"
        await service.stop()

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        account = mail_store.get_account(connection, "outlook")
        cursor = mail_store.get_cursor(connection, account["id"])
        candidate = connection.execute(
            "SELECT review_reasons FROM mail_event_candidates ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    assert graph.body_calls == 1
    assert auth.calls == 2
    assert cursor["graph_delta_link"] == NEW_DELTA_LINK
    assert candidate is not None
    assert "body_missing" in json.loads(candidate["review_reasons"])


def test_outlook_disconnect_does_not_clear_database_when_cache_delete_fails(
    client, tmp_path, monkeypatch
) -> None:
    account, _ = _connected_outlook(client.app.state.paths)
    cache_path = tmp_path / "secure" / "msal.cache"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"encrypted-cache-fixture")

    from backend.mail import service as service_module

    monkeypatch.setattr(service_module, "default_msal_cache_path", lambda: cache_path)
    real_unlink = service_module._unlink_secure

    def fail_cache_delete(path: Path) -> None:
        if path == cache_path:
            raise SecureStorageUnavailable("fixture-delete-failure")
        real_unlink(path)

    monkeypatch.setattr(service_module, "_unlink_secure", fail_cache_delete)
    service = MailService(client.app.state.paths, scheduler_enabled=False)

    async def run() -> None:
        with pytest.raises(ApiError) as raised:
            await service.disconnect("outlook")
        assert raised.value.status_code == 503
        assert raised.value.code == "credential_store_unavailable"

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        current = mail_store.get_account(connection, "outlook")
        cursor = mail_store.get_cursor(connection, account["id"])
    finally:
        connection.close()
    assert cache_path.read_bytes() == b"encrypted-cache-fixture"
    assert current["status"] == "connected"
    assert current["public_client_id"] == OLD_CLIENT_ID
    assert cursor["graph_delta_link"] == OLD_DELTA_LINK


def test_outlook_disconnect_removes_only_strictly_named_cache_orphans(
    client, tmp_path, monkeypatch
) -> None:
    account, _ = _connected_outlook(client.app.state.paths)
    cache_path = tmp_path / "secure" / "msal.cache"
    cache_path.parent.mkdir(parents=True)
    active_files = [cache_path, Path(f"{cache_path}.lockfile")]
    orphan_id = "a" * 32
    orphan_files = [
        cache_path.parent / f"msal.{orphan_id}.cache",
        cache_path.parent / f"msal.{orphan_id}.cache.lockfile",
        cache_path.parent / f"msal.{orphan_id}.backup",
        cache_path.parent / f"msal.{orphan_id}.backup.lockfile",
    ]
    unrelated_files = [
        cache_path.parent / "msal.not-a-uuid.cache",
        cache_path.parent / "other.backup",
    ]
    for fixture_path in [*active_files, *orphan_files, *unrelated_files]:
        fixture_path.write_bytes(b"encrypted-fixture")

    from backend.mail import service as service_module

    monkeypatch.setattr(service_module, "default_msal_cache_path", lambda: cache_path)
    service = MailService(client.app.state.paths, scheduler_enabled=False)

    asyncio.run(service.disconnect("outlook"))

    assert all(not fixture_path.exists() for fixture_path in active_files)
    assert all(not fixture_path.exists() for fixture_path in orphan_files)
    assert all(fixture_path.is_file() for fixture_path in unrelated_files)
    connection = open_connection(client.app.state.paths)
    try:
        current = mail_store.get_account(connection, "outlook")
        cursor = mail_store.get_cursor(connection, account["id"])
    finally:
        connection.close()
    assert current["status"] == "disconnected"
    assert cursor is None


def test_outlook_startup_retries_failed_staging_cache_cleanup(
    client, tmp_path, monkeypatch, caplog
) -> None:
    cache_path = tmp_path / "secure" / "msal.cache"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"active-encrypted-fixture")
    orphan = cache_path.parent / f"msal.{'b' * 32}.cache"
    orphan.write_bytes(b"orphan-encrypted-fixture")

    from backend.mail import service as service_module

    real_unlink = service_module._unlink_secure

    def fail_orphan_delete(path: Path) -> None:
        if path == orphan:
            raise SecureStorageUnavailable("fixture-delete-failure")
        real_unlink(path)

    monkeypatch.setattr(service_module, "_unlink_secure", fail_orphan_delete)
    first = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_cache_path_factory=lambda: cache_path,
    )

    async def first_start() -> None:
        await first.start()
        await first.stop()

    asyncio.run(first_start())
    assert orphan.is_file()
    assert cache_path.is_file()
    assert "mail_outlook_staging_cleanup_failed" in caplog.text

    monkeypatch.setattr(service_module, "_unlink_secure", real_unlink)
    second = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_cache_path_factory=lambda: cache_path,
    )

    async def second_start() -> None:
        await second.start()
        await second.stop()

    asyncio.run(second_start())
    assert not orphan.exists()
    assert cache_path.read_bytes() == b"active-encrypted-fixture"


class _SlowInteractiveAuth:
    def __init__(
        self,
        client_id: str,
        *,
        cache_path: Path | None = None,
        started: threading.Event,
        release: threading.Event,
        finished: threading.Event,
    ) -> None:
        self.client_id = client_id
        self.cache_path = cache_path
        self.started = started
        self.release = release
        self.finished = finished

    def acquire_interactive(self, *, timeout: int = 300) -> str:
        assert timeout == 300
        assert self.cache_path is not None
        self.started.set()
        self.release.wait(timeout=5)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_bytes(b"late-encrypted-cache")
        self.finished.set()
        return "late-fixture-token"


def test_outlook_interactive_timeout_cleans_cache_after_worker_finishes(
    client, tmp_path, monkeypatch
) -> None:
    from backend.mail import service as service_module

    cache_path = tmp_path / "secure" / "msal.cache"
    monkeypatch.setattr(service_module, "default_msal_cache_path", lambda: cache_path)
    real_wait_for = asyncio.wait_for

    async def short_wait_for(awaitable, timeout):
        del timeout
        return await real_wait_for(awaitable, timeout=0.01)

    monkeypatch.setattr(service_module.asyncio, "wait_for", short_wait_for)
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    auth_instances: list[_SlowInteractiveAuth] = []

    def auth_factory(client_id: str, *, cache_path: Path | None = None):
        auth = _SlowInteractiveAuth(
            client_id,
            cache_path=cache_path,
            started=started,
            release=release,
            finished=finished,
        )
        auth_instances.append(auth)
        return auth

    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_auth_factory=auth_factory,
    )
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        account = mail_store.ensure_account(connection, "outlook")

    async def run() -> None:
        with pytest.raises(TimeoutError):
            await service._connect_outlook(
                account,
                OutlookConnectRequest(client_id=NEW_CLIENT_ID),
            )
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        assert not finished.is_set()
        release.set()
        for _ in range(200):
            temp_path = auth_instances[0].cache_path
            if finished.is_set() and temp_path is not None and not temp_path.exists():
                break
            await asyncio.sleep(0.005)

    asyncio.run(run())

    temp_path = auth_instances[0].cache_path
    assert finished.is_set()
    assert temp_path is not None
    assert not temp_path.exists()
    assert not Path(f"{temp_path}.lockfile").exists()
    assert not cache_path.exists()


def test_outlook_reconnect_restores_previous_cache_when_database_write_fails(
    client, tmp_path, monkeypatch
) -> None:
    account, original_generation = _connected_outlook(client.app.state.paths)
    cache_path = tmp_path / "secure" / "msal.cache"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"previous-encrypted-cache")

    from backend.mail import service as service_module

    monkeypatch.setattr(service_module, "default_msal_cache_path", lambda: cache_path)
    graph = GraphScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_auth_factory=FakeOutlookAuth,
        graph_client_factory=graph.client,
    )

    def fail_cursor_write(*_args, **_kwargs):
        raise RuntimeError("fixture-database-failure")

    monkeypatch.setattr(mail_store, "save_graph_cursor", fail_cursor_write)

    async def run() -> None:
        operation = service.start_connect(
            "outlook",
            OutlookConnectRequest(client_id=NEW_CLIENT_ID),
        )
        result = await _finish(service, operation.id)
        assert result.status == "failed"
        await service.stop()

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        current = mail_store.get_account(connection, "outlook")
        cursor = mail_store.get_cursor(connection, account["id"])
    finally:
        connection.close()
    assert cache_path.read_bytes() == b"previous-encrypted-cache"
    assert current["public_client_id"] == OLD_CLIENT_ID
    assert current["connection_generation"] == original_generation
    assert cursor["graph_delta_link"] == OLD_DELTA_LINK
    assert list(cache_path.parent.glob("*.backup")) == []


def test_outlook_reconnect_keeps_backup_until_database_transaction_commits(
    client, tmp_path, monkeypatch
) -> None:
    account, original_generation = _connected_outlook(client.app.state.paths)
    cache_path = tmp_path / "secure" / "msal.cache"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"previous-encrypted-cache")

    from backend.mail import service as service_module

    monkeypatch.setattr(service_module, "default_msal_cache_path", lambda: cache_path)
    graph = GraphScenario()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_auth_factory=FakeOutlookAuth,
        graph_client_factory=graph.client,
    )
    real_transaction = application_store.open_connection_tx

    @contextmanager
    def fail_during_transaction_exit(paths):
        with real_transaction(paths) as connection:
            yield connection
            raise RuntimeError("fixture-commit-boundary-failure")

    monkeypatch.setattr(
        application_store,
        "open_connection_tx",
        fail_during_transaction_exit,
    )

    async def run() -> None:
        with pytest.raises(RuntimeError, match="commit-boundary"):
            await service._connect_outlook(
                account,
                OutlookConnectRequest(client_id=NEW_CLIENT_ID),
            )

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        current = mail_store.get_account(connection, "outlook")
        cursor = mail_store.get_cursor(connection, account["id"])
    finally:
        connection.close()
    assert cache_path.read_bytes() == b"previous-encrypted-cache"
    assert current["public_client_id"] == OLD_CLIENT_ID
    assert current["connection_generation"] == original_generation
    assert cursor["graph_delta_link"] == OLD_DELTA_LINK
    assert list(cache_path.parent.glob("*.backup")) == []


class _JsonResponse:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self.headers: dict[str, str] = {}
        self._payload = payload
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> dict:
        return self._payload


class _PagingHttp:
    def __init__(self, responses: list[_JsonResponse]) -> None:
        self.responses = responses
        self.authorization_headers: list[str] = []

    def get(self, _url: str, *, headers: dict, **_kwargs):
        self.authorization_headers.append(headers["Authorization"])
        return self.responses.pop(0)


def test_outlook_sync_refreshes_access_token_for_each_graph_request(client) -> None:
    account, _ = _connected_outlook(client.app.state.paths)
    next_link = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
        "$skiptoken=fixture-page-2"
    )
    final_link = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
        "$deltatoken=fixture-refreshed"
    )
    http = _PagingHttp(
        [
            _JsonResponse({"value": [], "@odata.nextLink": next_link}),
            _JsonResponse({"value": [], "@odata.deltaLink": final_link}),
        ]
    )
    auth = _SilentAuth()
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_auth_factory=lambda _client_id: auth,
        graph_client_factory=lambda provider: GraphMailClient(
            provider,
            http_client=http,
        ),
    )

    async def run() -> None:
        operation = service.start_sync("outlook")
        assert (await _finish(service, operation.id)).status == "succeeded"
        await service.stop()

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        cursor = mail_store.get_cursor(connection, account["id"])
    finally:
        connection.close()
    assert auth.calls == 2
    assert http.authorization_headers == [
        "Bearer fixture-token-1",
        "Bearer fixture-token-2",
    ]
    assert cursor["graph_delta_link"] == final_link


class _BlockingGraph:
    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self.started = started
        self.release = release

    def client(self, token_provider):
        scenario = self

        class Client:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def fetch_delta(self, *, delta_link=None, since=None):
                assert delta_link == OLD_DELTA_LINK
                assert since is None
                token_provider()
                scenario.started.set()
                scenario.release.wait(timeout=5)
                return GraphDeltaResult((), NEW_DELTA_LINK)

        return Client()


def test_pause_during_outlook_sync_remains_paused_after_success(client) -> None:
    _connected_outlook(client.app.state.paths)
    started = threading.Event()
    release = threading.Event()
    graph = _BlockingGraph(started, release)
    service = MailService(
        client.app.state.paths,
        scheduler_enabled=False,
        outlook_auth_factory=lambda _client_id: _SilentAuth(),
        graph_client_factory=graph.client,
    )

    async def run() -> None:
        operation = service.start_sync("outlook")
        for _ in range(200):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        paused = await service.pause("outlook")
        assert paused.status == "paused"
        release.set()
        assert (await _finish(service, operation.id)).status == "succeeded"
        await service.stop()

    asyncio.run(run())

    connection = open_connection(client.app.state.paths)
    try:
        account = mail_store.get_account(connection, "outlook")
    finally:
        connection.close()
    assert account["status"] == "paused"
