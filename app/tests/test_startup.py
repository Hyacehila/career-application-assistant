"""Start-BoardService.ps1 process behavior without touching the real overlay."""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PORT = 8000

SYNTHETIC_SERVER = r'''"""Synthetic loopback health fixture; no database or mail runtime."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_GET(self):
        if self.path != "/api/health":
            self.send_error(404)
            return
        payload = json.dumps({
            "status": "ok",
            "database": "available",
            "schema_version": 5,
            "service": "career-application-assistant",
            "mode": "standard",
            "synthetic_data": False,
            "mail_ingestion": True,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
'''


def _port_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(("127.0.0.1", PORT)) != 0


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/api/health", timeout=2
        ) as response:
            body = json.load(response)
            return (
                response.status == 200
                and body.get("service") == "career-application-assistant"
                and body.get("mode") == "standard"
                and body.get("synthetic_data") is False
            )
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _copy_startup_fixture(tmp_path: Path) -> Path:
    """Create a synthetic public service without a database or secure storage."""

    fixture = tmp_path / "public-repository"
    (fixture / "app").mkdir(parents=True)
    (fixture / "scripts").mkdir()
    (fixture / "app" / "server.py").write_text(SYNTHETIC_SERVER, encoding="utf-8")
    shutil.copy2(
        REPO_ROOT / "scripts" / "Start-BoardService.ps1",
        fixture / "scripts" / "Start-BoardService.ps1",
    )
    return fixture


def _run_script(fixture: Path) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "pwsh is required for this test"
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join(
        [str(Path(sys.executable).resolve().parent), environment.get("PATH", "")]
    )
    return subprocess.run(
        [pwsh, "-NoProfile", "-File", str(fixture / "scripts" / "Start-BoardService.ps1")],
        cwd=str(fixture),
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _stop_exact_pid(pid: int) -> None:
    """Stop only the process returned by the script under test."""

    powershell = shutil.which("pwsh") or shutil.which("powershell")
    assert powershell is not None, "PowerShell is required for process cleanup"
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-Command",
            f"Stop-Process -Id {int(pid)} -Force -ErrorAction Stop",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt", reason="PowerShell process cleanup is Windows-only")
def test_stop_exact_pid_terminates_only_the_captured_process() -> None:
    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    sentinel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _stop_exact_pid(target.pid)
        target.wait(timeout=10)
        assert sentinel.poll() is None
    finally:
        if target.poll() is None:
            target.terminate()
            target.wait(timeout=10)
        if sentinel.poll() is None:
            sentinel.terminate()
            sentinel.wait(timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell startup contract is Windows-only")
def test_startup_script_starts_service_and_is_idempotent(tmp_path: Path) -> None:
    if not _port_free():
        pytest.skip("port 8000 is busy; another service is running")

    fixture = _copy_startup_fixture(tmp_path)
    started_pid: int | None = None
    try:
        first = _run_script(fixture)
        assert first.returncode == 0, first.stdout + first.stderr
        match = re.search(r"\(pid (\d+)\)", first.stdout)
        assert match is not None, first.stdout
        started_pid = int(match.group(1))
        assert _healthy()

        second = _run_script(fixture)
        assert second.returncode == 0, second.stdout + second.stderr
        assert "already running" in second.stdout
    finally:
        if started_pid is not None:
            _stop_exact_pid(started_pid)


@pytest.mark.skipif(os.name != "nt", reason="PowerShell startup contract is Windows-only")
def test_startup_script_fails_when_unknown_service_owns_port(tmp_path: Path) -> None:
    if not _port_free():
        pytest.skip("port 8000 is busy; another service is running")

    fixture = _copy_startup_fixture(tmp_path)
    blocker = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=str(fixture),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        blocker.wait(timeout=0.5)
        raise AssertionError("port blocker exited before the test")
    except subprocess.TimeoutExpired:
        pass

    try:
        result = _run_script(fixture)
        assert result.returncode != 0
        assert "FAIL" in result.stdout
    finally:
        blocker.terminate()
        blocker.wait(timeout=10)
