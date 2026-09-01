"""Stage 1: database path, migration, health and request guard behavior."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app import init_database
from backend.config import Paths
from backend.database import DatabaseUnavailableError, open_connection
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


def test_v3_and_v4_migrations_preserve_data_and_add_completion_date(private_root: Path) -> None:
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

        assert ensure_migrations(connection) == 4
        assert ensure_migrations(connection) == 4
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
        assert ensure_migrations(connection) == 4
    finally:
        connection.close()


def test_unknown_schema_version_stops_startup(private_root: Path) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    init_database(paths)

    connection = open_connection(paths)
    connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (5, 'x')")
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
    assert body["schema_version"] == 4
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
    connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (5, 'x')")
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
