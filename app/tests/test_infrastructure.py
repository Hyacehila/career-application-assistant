"""Stage 1: database path, migration, health and request guard behavior."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from backend.app import init_database
from backend.config import Paths
from backend.database import DatabaseUnavailableError, open_connection
from backend.mail.store import message_fingerprint
from backend.migrations import MIGRATIONS, SchemaVersionError, ensure_migrations


def test_first_run_creates_database_only_at_fixed_path(private_root: Path, db_path: Path) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    assert not db_path.exists()

    init_database(paths)

    assert db_path.exists()
    stray = [item for item in private_root.parent.rglob("*.sqlite")]
    assert [str(p) for p in stray] == [str(db_path)]


def test_missing_private_overlay_creates_no_database(tmp_path: Path) -> None:
    paths = Paths(repository_root=tmp_path, private_root=tmp_path / "private")

    with pytest.raises(DatabaseUnavailableError):
        open_connection(paths)

    assert list(tmp_path.rglob("*.sqlite")) == []


def test_migrations_are_idempotent(private_root: Path) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    init_database(paths)

    connection = open_connection(paths)
    try:
        ensure_migrations(connection)
        ensure_migrations(connection)
    finally:
        connection.close()

    init_database(paths)


def test_v3_through_v6_migrations_preserve_imap_data_and_add_completion_date(private_root: Path) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    connection = open_connection(paths)
    try:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.executescript(MIGRATIONS[1])
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, 'fixture')"
        )
        connection.executescript(MIGRATIONS[2])
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (2, 'fixture')"
        )
        connection.execute(
            """
            INSERT INTO mail_accounts (
                id, provider, status, public_client_id, history_window,
                last_attempt_at, last_success_at, next_retry_at, last_error_code,
                created_at, updated_at, disconnected_at
            ) VALUES (
                'legacy-account', 'qq', 'connected', NULL, 'new_only',
                NULL, NULL, NULL, NULL, 'fixture', 'fixture', NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO applications (
                id, company_name, job_title, current_status, created_at, updated_at
            ) VALUES (1, '迁移测试公司', '迁移测试岗位', 'assessment', 'fixture', 'fixture')
            """
        )
        connection.execute(
            """
            INSERT INTO application_events (
                id, application_id, stage, event_date, source, created_at, updated_at
            ) VALUES (1, 1, 'assessment', '2026-08-20', 'manual_ui', 'fixture', 'fixture')
            """
        )
        connection.commit()

        assert ensure_migrations(connection) == 6
        assert ensure_migrations(connection) == 6
        row = connection.execute(
            "SELECT * FROM mail_accounts WHERE id = 'legacy-account'"
        ).fetchone()
        columns = {
            item["name"] for item in connection.execute("PRAGMA table_info(mail_accounts)")
        }
        event_columns = {
            item["name"]
            for item in connection.execute("PRAGMA table_info(application_events)")
        }
        event_row = connection.execute(
            "SELECT stage, event_date, completed_date FROM application_events WHERE id = 1"
        ).fetchone()
    finally:
        connection.close()

    assert {
        "connection_generation",
        "credential_ref",
        "pending_credential_ref",
        "previous_credential_ref",
    } <= columns
    assert row["connection_generation"] == "legacy-account"
    assert row["credential_ref"] == "legacy-account"
    assert row["pending_credential_ref"] is None
    assert row["previous_credential_ref"] is None
    assert "completed_date" in event_columns
    assert dict(event_row) == {
        "stage": "assessment",
        "event_date": "2026-08-20",
        "completed_date": None,
    }


def test_failed_migration_rolls_back_and_can_be_retried(
    private_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    connection = open_connection(paths)
    try:
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.executescript(MIGRATIONS[1])
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, 'fixture')"
        )
        connection.executescript(MIGRATIONS[2])
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (2, 'fixture')"
        )
        connection.commit()

        original = MIGRATIONS[3]
        broken = original.replace(
            "ALTER TABLE mail_accounts ADD COLUMN credential_ref TEXT;",
            "THIS IS NOT VALID SQL;",
        )
        monkeypatch.setitem(MIGRATIONS, 3, broken)
        with pytest.raises(sqlite3.OperationalError):
            ensure_migrations(connection)

        columns = {
            item["name"] for item in connection.execute("PRAGMA table_info(mail_accounts)")
        }
        version = connection.execute(
            "SELECT max(version) AS version FROM schema_migrations"
        ).fetchone()["version"]
        assert "connection_generation" not in columns
        assert version == 2

        monkeypatch.setitem(MIGRATIONS, 3, original)
        assert ensure_migrations(connection) == 6
    finally:
        connection.close()


def test_v4_to_v5_removes_outlook_local_state_but_preserves_timeline_and_imap(
    private_root: Path,
) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    connection = open_connection(paths)
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version in range(1, 5):
            connection.executescript(MIGRATIONS[version])
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, 'fixture')",
                (version,),
            )
        connection.execute(
            """
            INSERT INTO applications (
                id, company_name, job_title, current_status, created_at, updated_at
            ) VALUES (1, '示例公司', '示例岗位', 'interview_1', 'fixture', 'fixture')
            """
        )
        connection.execute(
            """
            INSERT INTO application_events (
                id, application_id, stage, event_date, scheduled_date,
                timezone, source, created_at, updated_at
            ) VALUES (
                1, 1, 'interview_1', '2026-08-20', '2026-08-25',
                'Asia/Shanghai', 'email_extract', 'fixture', 'fixture'
            )
            """
        )
        account_sql = """
            INSERT INTO mail_accounts (
                id, provider, status, public_client_id, history_window,
                created_at, updated_at, connection_generation, credential_ref
            ) VALUES (?, ?, 'connected', ?, 'last_30_days', 'fixture', 'fixture', ?, ?)
        """
        connection.execute(account_sql, ("outlook-old", "outlook", "client-id", "gen-o", None))
        connection.execute(account_sql, ("qq-old", "qq", None, "gen-q", "credential-q"))
        connection.execute(
            """
            INSERT INTO mail_sync_cursors (
                account_id, graph_delta_link, initial_cutoff_at, updated_at
            ) VALUES ('outlook-old', 'raw-graph-delta', 'fixture', 'fixture')
            """
        )
        connection.execute(
            """
            INSERT INTO mail_sync_cursors (
                account_id, imap_uidvalidity, imap_last_uid, initial_cutoff_at, updated_at
            ) VALUES ('qq-old', 7001, 41, 'fixture', 'fixture')
            """
        )
        candidate_sql = """
            INSERT INTO mail_event_candidates (
                account_id, fingerprint, state, commit_mode, proposed_stage,
                event_date, timezone, confidence, matched_application_id,
                application_event_id, review_reasons, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '2026-08-20', 'Asia/Shanghai', 100, 1, ?, '[]', 'fixture', 'fixture')
        """
        connection.execute(
            candidate_sql,
            ("outlook-old", "outlook-fingerprint", "committed", "auto", "interview_1", 1),
        )
        qq_source_key = "gen-q:7001:41"
        qq_fingerprint = hashlib.sha256(
            f"qq-old\0qq\0inbox\0{qq_source_key}".encode("utf-8")
        ).hexdigest()
        connection.execute(
            candidate_sql,
            ("qq-old", qq_fingerprint, "pending", None, "offer", None),
        )
        connection.commit()

        assert ensure_migrations(connection) == 6
        assert [row["provider"] for row in connection.execute("SELECT provider FROM mail_accounts")] == [
            "qq"
        ]
        cursor = connection.execute("SELECT * FROM mail_sync_cursors").fetchone()
        assert cursor["account_id"] == "qq-old"
        assert cursor["imap_uidvalidity"] == 7001
        assert cursor["imap_last_uid"] == 41
        candidates = connection.execute(
            "SELECT provider, fingerprint FROM mail_event_candidates"
        ).fetchall()
        assert [(row["provider"], row["fingerprint"]) for row in candidates] == [
            ("qq", qq_fingerprint)
        ]
        assert message_fingerprint(
            "qq", qq_source_key, fingerprint_scope="qq-old"
        ) == qq_fingerprint
        event = connection.execute("SELECT * FROM application_events WHERE id = 1").fetchone()
        assert event["stage"] == "interview_1"
        assert event["source"] == "email_extract"
        account_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(mail_accounts)")
        }
        cursor_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(mail_sync_cursors)")
        }
        candidate_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(mail_event_candidates)")
        }
        assert "public_client_id" not in account_columns
        assert "graph_delta_link" not in cursor_columns
        assert "account_id" not in candidate_columns
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_v5_to_v6_releases_transient_run_and_allows_repeated_header_decisions(
    private_root: Path,
) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    connection = open_connection(paths)
    try:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        for version in range(1, 6):
            connection.executescript(MIGRATIONS[version])
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, 'fixture')",
                (version,),
            )
        connection.execute(
            """
            UPDATE outlook_connector_state
            SET status = 'connecting', last_success_at = '2026-09-01T00:00:00+00:00',
                active_run_id = 'old-run', lease_expires_at = '2099-01-01T00:00:00+00:00',
                headers_seen = 1, bodies_seen = 1
            WHERE singleton_id = 1
            """
        )
        connection.execute(
            """
            INSERT INTO outlook_scan_windows (
                id, window_kind, start_at, end_at, next_from_index,
                leased_by_run_id, lease_start_index, lease_headers_seen,
                lease_limit, created_at, updated_at
            ) VALUES (
                'window-1', 'backfill', '2026-08-01T00:00:00+00:00',
                '2026-09-01T00:00:00+00:00', 4, 'old-run', 4, 1, 100,
                'fixture', 'fixture'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO outlook_connector_body_tokens (
                run_id, token_hash, fingerprint, header_hash, consumed, created_at
            ) VALUES ('old-run', 'old-token', 'same-fingerprint', 'old-header', 0, 'fixture')
            """
        )
        connection.commit()

        assert ensure_migrations(connection) == 6
        state = connection.execute(
            "SELECT * FROM outlook_connector_state WHERE singleton_id = 1"
        ).fetchone()
        window = connection.execute(
            "SELECT * FROM outlook_scan_windows WHERE id = 'window-1'"
        ).fetchone()
        assert state["status"] == "connected"
        assert state["active_run_id"] is None
        assert state["lease_expires_at"] is None
        assert state["headers_seen"] == 0
        assert state["bodies_seen"] == 0
        assert window["next_from_index"] == 4
        assert window["leased_by_run_id"] is None
        assert window["lease_start_index"] is None
        assert window["lease_headers_seen"] == 0
        assert window["lease_limit"] is None
        assert connection.execute(
            "SELECT count(*) FROM outlook_connector_body_tokens"
        ).fetchone()[0] == 0

        connection.executemany(
            """
            INSERT INTO outlook_connector_body_tokens (
                run_id, token_hash, fingerprint, header_hash, consumed, created_at
            ) VALUES ('new-run', ?, 'same-fingerprint', ?, 0, 'fixture')
            """,
            [("token-1", "header-1"), ("token-2", "header-2")],
        )
        assert connection.execute(
            "SELECT count(*) FROM outlook_connector_body_tokens WHERE fingerprint = 'same-fingerprint'"
        ).fetchone()[0] == 2
    finally:
        connection.close()


def test_unknown_schema_version_stops_startup(private_root: Path) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    init_database(paths)

    connection = open_connection(paths)
    connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (7, 'x')")
    connection.commit()
    connection.close()

    with pytest.raises(SchemaVersionError):
        init_database(paths)


def test_health_reports_ok_schema_version(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "available"
    assert body["schema_version"] == 6
    assert body["service"] == "career-application-assistant"
    assert body["mode"] == "test"
    assert body["synthetic_data"] is False
    assert body["mail_ingestion"] is True


def test_health_returns_503_when_database_is_unavailable(client, private_root: Path) -> None:
    unavailable = private_root.with_name("private-unavailable")
    private_root.rename(unavailable)
    try:
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.json() == {
            "status": "degraded",
            "database": "unavailable",
            "schema_version": None,
            "service": "career-application-assistant",
            "mode": "test",
            "synthetic_data": False,
            "mail_ingestion": True,
        }
    finally:
        unavailable.rename(private_root)


def test_health_returns_503_for_incompatible_schema(client) -> None:
    connection = open_connection(client.app.state.paths)
    connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (7, 'x')")
    connection.commit()
    connection.close()
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["schema_version"] is None


def test_request_validation_errors_use_uniform_shape(client) -> None:
    responses = [
        client.post(
            "/api/applications",
            json={"company_name": "示例科技", "event_date": "2026-08-01"},
        ),
        client.get("/api/applications", params={"page": 0}),
        client.get("/api/applications/not-an-id"),
    ]
    for response in responses:
        assert response.status_code == 422
        body = response.json()
        assert body["code"] == "validation_error"
        assert body["message"] == "Request validation failed."
        assert body["details"]["errors"]


def test_ipv6_loopback_host_is_allowed(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        response = test_client.get("/api/health", headers={"host": "[::1]:8000"})
        assert response.status_code == 200


def test_non_loopback_host_is_rejected(app) -> None:
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        response = test_client.get("/api/health", headers={"host": "example.com"})
        assert response.status_code == 400
        assert response.json()["code"] == "host_not_allowed"


def test_non_json_post_is_rejected(client) -> None:
    response = client.post(
        "/api/applications",
        content=b"company=a&job=b",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "not_json"


def test_non_json_patch_is_rejected(client) -> None:
    response = client.patch(
        "/api/applications/1",
        content=b"{}",
        headers={"content-type": "text/plain"},
    )
    assert response.status_code == 415


def test_cross_origin_write_is_rejected(client) -> None:
    response = client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "前端工程师",
            "event_date": "2026-08-01",
        },
        headers={"origin": "https://malicious.example"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "origin_not_allowed"


def test_same_loopback_origin_write_is_allowed(client) -> None:
    response = client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "前端工程师",
            "event_date": "2026-08-01",
        },
        headers={"origin": "http://127.0.0.1:8000"},
    )
    assert response.status_code == 201
