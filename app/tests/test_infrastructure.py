"""Stage 1: database path, migration, health and request guard behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import init_database
from backend.config import Paths
from backend.database import DatabaseUnavailableError, open_connection
from backend.migrations import SchemaVersionError, ensure_migrations


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


def test_unknown_schema_version_stops_startup(private_root: Path) -> None:
    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    init_database(paths)

    connection = open_connection(paths)
    connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (2, 'x')")
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
    assert body["schema_version"] == 1


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
        }
    finally:
        unavailable.rename(private_root)


def test_health_returns_503_for_incompatible_schema(client) -> None:
    connection = open_connection(client.app.state.paths)
    connection.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (2, 'x')")
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
