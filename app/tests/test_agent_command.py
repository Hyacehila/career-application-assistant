"""Integration coverage for the typed Agent PowerShell command."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMAND_SCRIPT = REPOSITORY_ROOT / "scripts" / "Invoke-BoardAgent.ps1"
MOCK_SERVER = REPOSITORY_ROOT / "app" / "tests" / "e2e" / "mock_server.py"
BASE_URL = "http://127.0.0.1:8000"


def _port_is_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(("127.0.0.1", 8000)) != 0


def _wait_until_healthy(process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("Mock board server exited before becoming healthy.")
        try:
            with urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise AssertionError("Mock board server did not become healthy.")


@contextmanager
def _running_mock_server():
    if not _port_is_free():
        pytest.skip("port 8000 is busy")
    fixture_root = Path(tempfile.mkdtemp(prefix="career-board-e2e-"))
    database_path = fixture_root / "applications.sqlite"
    creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [
            sys.executable,
            str(MOCK_SERVER),
            "--database",
            str(database_path),
            "--port",
            "8000",
        ],
        cwd=REPOSITORY_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    try:
        _wait_until_healthy(process)
        yield
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        shutil.rmtree(fixture_root, ignore_errors=True)


def _run_agent_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is required")
    environment = os.environ.copy()
    environment["CAREER_APPLICATION_ASSISTANT_ALLOW_TEST_MODE"] = "1"
    return subprocess.run(
        [pwsh, "-NoProfile", "-File", str(COMMAND_SCRIPT), *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )


def _get_json(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=3) as response:
        return json.load(response)


def test_agent_command_fills_then_updates_by_exact_record_id():
    with _running_mock_server():
        fill = _run_agent_command(
            "-Action",
            "FillCompleted",
            "-CompanyName",
            "命令封装测试公司",
            "-JobTitle",
            "测试岗位",
            "-JobCode",
            "CMD-001",
            "-ApplicationType",
            "实习",
            "-Location",
            "上海",
            "-JobSource",
            "本地集成测试",
            "-JobUrl",
            "https://jobs.example.test/cmd-001?tracking=removed#apply",
            "-FilledAt",
            "2026-08-29T09:00:00+08:00",
        )
        assert fill.returncode == 0, fill.stdout + fill.stderr
        fill_result = json.loads(fill.stdout)
        assert fill_result == {
            "ok": True,
            "action": "fill_completed",
            "application_id": fill_result["application_id"],
            "current_status": "pending_review",
        }

        application_id = fill_result["application_id"]
        detail = _get_json(f"/api/applications/{application_id}")
        assert detail["application"]["job_url"] == "https://jobs.example.test/cmd-001"

        update = _run_agent_command(
            "-Action",
            "StatusUpdate",
            "-ApplicationId",
            str(application_id),
            "-Stage",
            "applied",
            "-EventDate",
            "2026-08-29",
            "-EventSource",
            "user_confirmation",
        )
        assert update.returncode == 0, update.stdout + update.stderr
        update_result = json.loads(update.stdout)
        assert update_result["application_id"] == application_id
        assert update_result["current_status"] == "applied"
        assert update_result["event_stage"] == "applied"

        missing_date = _run_agent_command(
            "-Action",
            "StatusUpdate",
            "-ApplicationId",
            str(application_id),
            "-Stage",
            "assessment",
            "-EventDate",
            "2026-08-29",
            "-EventSource",
            "email_extract",
        )
        assert missing_date.returncode != 0
        assert "requires ScheduledDate or DeadlineDate" in missing_date.stderr
