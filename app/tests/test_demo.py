"""Explicit standard, test, and isolated synthetic Demo runtime contracts."""

from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app, create_demo_app, init_database
from backend.clock import CN_TZ
from backend.config import Paths
from backend.database import open_connection
from backend.demo import (
    UnsafeDemoDirectoryError,
    cleanup_demo_directory,
    reset_demo_data,
    validate_demo_directory,
)


@pytest.fixture
def demo_directory():
    directory = Path(tempfile.gettempdir()) / (
        f"career-application-assistant-demo-{uuid4().hex}"
    )
    directory.mkdir(mode=0o700)
    try:
        yield directory
    finally:
        if directory.exists():
            cleanup_demo_directory(directory)


@pytest.fixture
def demo_paths(demo_directory: Path) -> Paths:
    paths = Paths(repository_root=Path(__file__).resolve().parents[2], private_root=demo_directory)
    init_database(paths)
    reset_demo_data(paths)
    return paths


@pytest.fixture
def demo_client(demo_paths: Paths):
    with TestClient(
        create_demo_app(demo_paths), base_url="http://127.0.0.1:8001"
    ) as test_client:
        yield test_client


def test_standard_factory_uses_only_default_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_root = tmp_path / "synthetic-private"
    private_root.mkdir()
    paths = Paths(repository_root=tmp_path, private_root=private_root)
    init_database(paths)
    monkeypatch.setattr("backend.app.default_paths", lambda: paths)

    standard_app = create_app()
    assert standard_app.state.paths == paths
    assert standard_app.title == "求职投递助手 / Career Application Assistant"
    assert standard_app.state.mode == "standard"
    assert standard_app.state.synthetic_data is False
    assert standard_app.state.mail_ingestion is True
    with TestClient(standard_app, base_url="http://127.0.0.1:8000") as standard_client:
        standard_health = standard_client.get("/api/health").json()
    assert standard_health["mode"] == "standard"
    assert standard_health["synthetic_data"] is False
    assert standard_health["mail_ingestion"] is True
    with pytest.raises(TypeError):
        create_app(paths)  # type: ignore[call-arg]


def test_test_factory_keeps_mail_and_agent_routes_with_scheduler_disabled(app, client) -> None:
    assert app.state.mode == "test"
    assert app.state.mail_service.scheduler_enabled is False
    assert client.get("/api/mail/accounts").status_code == 200
    assert client.post("/api/agent/fill-completed", json={}).status_code == 422


def test_demo_health_seed_and_route_surface(demo_client: TestClient) -> None:
    health = demo_client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "database": "available",
        "schema_version": 6,
        "service": "career-application-assistant",
        "mode": "demo",
        "synthetic_data": True,
        "mail_ingestion": False,
    }

    response = demo_client.get("/api/applications", params={"page_size": 100})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 6
    assert body["counts"] == {
        "pending_review": 1,
        "applied": 1,
        "assessment": 1,
        "interview": 1,
        "ended": 2,
    }
    assert all("虚构" in item["company_name"] for item in body["items"])
    assert all(
        (urlsplit(item["job_url"]).hostname or "").endswith(".example.test")
        for item in body["items"]
    )
    assert demo_client.get("/api/mail/accounts").status_code == 404
    assert demo_client.post("/api/agent/fill-completed", json={}).status_code == 404


def test_demo_applied_events_use_explicit_user_confirmation(demo_paths: Paths) -> None:
    connection = open_connection(demo_paths)
    try:
        sources = connection.execute(
            "SELECT DISTINCT source FROM application_events WHERE stage = 'applied'"
        ).fetchall()
    finally:
        connection.close()
    assert [row["source"] for row in sources] == ["user_confirmation"]


def test_demo_dates_are_relative_to_the_shanghai_start_day(demo_paths: Paths) -> None:
    connection = open_connection(demo_paths)
    try:
        event_dates = [
            date.fromisoformat(row["event_date"])
            for row in connection.execute("SELECT event_date FROM application_events")
        ]
    finally:
        connection.close()
    anchor = datetime.now(CN_TZ).date()
    assert all(-40 <= (event_date - anchor).days <= 3 for event_date in event_dates)


def test_demo_reset_restores_six_records_after_crud(demo_client: TestClient) -> None:
    original = demo_client.get("/api/applications", params={"page_size": 100}).json()["items"]
    created = demo_client.post(
        "/api/applications",
        json={
            "company_name": "临时操作记录（虚构）",
            "job_title": "临时岗位（演示）",
            "job_url": "https://temporary.example.test/jobs/demo",
            "event_date": datetime.now(CN_TZ).date().isoformat(),
        },
    )
    assert created.status_code == 201
    assert demo_client.patch(
        f"/api/applications/{original[0]['id']}", json={"job_title": "已修改（演示）"}
    ).status_code == 200
    assert demo_client.delete(f"/api/applications/{original[1]['id']}").status_code == 204

    reset = demo_client.post("/api/demo/reset", json={})
    assert reset.status_code == 200
    assert reset.json() == {"ok": True, "records_seeded": 6}
    restored = demo_client.get("/api/applications", params={"page_size": 100}).json()
    assert restored["total"] == 6
    assert all(item["job_title"] != "已修改（演示）" for item in restored["items"])
    assert all(item["company_name"] != "临时操作记录（虚构）" for item in restored["items"])


def test_demo_reset_requires_exact_empty_json(demo_client: TestClient) -> None:
    assert demo_client.post("/api/demo/reset", json={"unexpected": True}).status_code == 422
    assert demo_client.post("/api/demo/reset").status_code == 415


def _rows(paths: Paths, table: str) -> list[tuple]:
    connection = open_connection(paths)
    try:
        return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY id")]
    finally:
        connection.close()


def test_demo_reset_rolls_back_as_one_transaction(
    demo_paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    before_applications = _rows(demo_paths, "applications")
    before_events = _rows(demo_paths, "application_events")
    from backend import demo

    original_create = demo.store.create_application
    calls = 0

    def fail_during_seed(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic seed failure")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(demo.store, "create_application", fail_during_seed)
    with pytest.raises(RuntimeError, match="synthetic seed failure"):
        reset_demo_data(demo_paths)

    assert _rows(demo_paths, "applications") == before_applications
    assert _rows(demo_paths, "application_events") == before_events


def test_demo_factory_never_constructs_mail_or_secure_storage(
    demo_paths: Paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.mail import credentials, service

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Demo touched the mail or secure-storage stack")

    monkeypatch.setattr(service, "MailService", forbidden)
    monkeypatch.setattr(credentials, "WindowsCredentialStore", forbidden)

    demo_app = create_demo_app(demo_paths)
    assert not hasattr(demo_app.state, "mail_service")
    with TestClient(demo_app, base_url="http://127.0.0.1:8001") as client:
        assert client.get("/api/health").status_code == 200


def test_demo_paths_reject_nested_or_misnamed_directories(tmp_path: Path) -> None:
    nested = tmp_path / f"career-application-assistant-demo-{uuid4().hex}"
    nested.mkdir()
    with pytest.raises(UnsafeDemoDirectoryError):
        validate_demo_directory(nested)

    direct = Path(tempfile.gettempdir()) / f"wrong-demo-{uuid4().hex}"
    direct.mkdir()
    try:
        with pytest.raises(UnsafeDemoDirectoryError):
            validate_demo_directory(direct)
        assert direct.exists()
    finally:
        shutil.rmtree(direct)


def test_demo_cleanup_refuses_nested_directory(tmp_path: Path) -> None:
    nested = tmp_path / f"career-application-assistant-demo-{uuid4().hex}"
    nested.mkdir()
    marker = nested / "must-remain.txt"
    marker.write_text("synthetic", encoding="utf-8")
    with pytest.raises(UnsafeDemoDirectoryError):
        cleanup_demo_directory(nested)
    assert marker.is_file()


def test_demo_cleanup_refuses_directory_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    marker = target / "must-remain.txt"
    marker.write_text("synthetic", encoding="utf-8")
    link = Path(tempfile.gettempdir()) / (
        f"career-application-assistant-demo-{uuid4().hex}"
    )
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlink unavailable: {exc.__class__.__name__}")
    try:
        with pytest.raises(UnsafeDemoDirectoryError):
            cleanup_demo_directory(link)
        assert marker.is_file()
    finally:
        link.unlink(missing_ok=True)


def test_demo_cleanup_refuses_junction_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    directory = Path(tempfile.gettempdir()) / (
        f"career-application-assistant-demo-{uuid4().hex}"
    )
    directory.mkdir(mode=0o700)
    marker = directory / "must-remain.txt"
    marker.write_text("synthetic", encoding="utf-8")
    path_type = type(directory)
    original_is_junction = path_type.is_junction

    def report_owned_directory_as_junction(self):
        if self.absolute() == directory.absolute():
            return True
        return original_is_junction(self)

    monkeypatch.setattr(path_type, "is_junction", report_owned_directory_as_junction)
    try:
        with pytest.raises(UnsafeDemoDirectoryError):
            cleanup_demo_directory(directory)
        assert marker.is_file()
    finally:
        shutil.rmtree(directory)


def test_demo_cleanup_removes_only_validated_session() -> None:
    directory = Path(tempfile.gettempdir()) / (
        f"career-application-assistant-demo-{uuid4().hex}"
    )
    directory.mkdir(mode=0o700)
    marker = directory / "session-only.txt"
    marker.write_text("synthetic", encoding="utf-8")
    cleanup_demo_directory(directory)
    assert not directory.exists()


def test_demo_server_is_fixed_and_cleans_its_session(monkeypatch: pytest.MonkeyPatch) -> None:
    import demo_server
    import uvicorn

    observed: dict[str, object] = {}

    def fake_run(app, **kwargs):
        observed["paths"] = app.state.paths
        observed.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["demo_server.py"])
    demo_server.main()

    paths = observed["paths"]
    assert isinstance(paths, Paths)
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 8001
    assert observed["access_log"] is False
    assert not paths.private_root.exists()


def test_demo_server_checks_lexical_entry_before_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import demo_server
    import uvicorn

    session = tmp_path / f"career-application-assistant-demo-{uuid4().hex}"
    cleaned: list[Path] = []
    monkeypatch.setattr(sys, "argv", ["demo_server.py"])
    monkeypatch.setattr(demo_server, "create_demo_session_directory", lambda: session)
    monkeypatch.setattr(demo_server, "build_demo_app", lambda _: object())
    monkeypatch.setattr(demo_server.os.path, "lexists", lambda _: True)
    monkeypatch.setattr(demo_server, "cleanup_demo_directory", cleaned.append)
    monkeypatch.setattr(uvicorn, "run", lambda *_args, **_kwargs: None)

    demo_server.main()

    assert cleaned == [session]


def test_demo_server_rejects_all_arguments_before_allocating_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import demo_server

    monkeypatch.setattr(sys, "argv", ["demo_server.py", "--port", "9000"])
    monkeypatch.setattr(
        demo_server,
        "create_demo_session_directory",
        lambda: (_ for _ in ()).throw(AssertionError("storage was allocated")),
    )
    with pytest.raises(SystemExit, match="does not accept"):
        demo_server.main()
