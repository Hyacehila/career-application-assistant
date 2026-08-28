"""Stage 3: Start-BoardService.ps1 auto-start behavior (real process, loopback only)."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PORT = 8000
SCRIPT = REPO_ROOT / "scripts" / "Start-BoardService.ps1"


def _port_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(("127.0.0.1", PORT)) != 0


def _healthy() -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/api/health", timeout=2
        ) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _run_script() -> subprocess.CompletedProcess:
    pwsh = shutil.which("pwsh")
    assert pwsh is not None, "pwsh is required for this test"
    return subprocess.run(
        [pwsh, "-NoProfile", "-File", str(SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_startup_script_starts_service_and_is_idempotent():
    if not os.name == "nt":
        return
    if not _port_free():
        import pytest

        pytest.skip("port 8000 is busy; another service is running")

    first = _run_script()
    assert first.returncode == 0, first.stdout + first.stderr
    assert "OK" in first.stdout
    assert _healthy()

    second = _run_script()
    assert second.returncode == 0, second.stdout + second.stderr
    assert "already running" in second.stdout

    # Clean up the service this test started.
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | "
         "ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0


def test_startup_script_fails_with_nonzero_exit_when_port_blocked():
    if not os.name == "nt":
        return
    if not _port_free():
        import pytest

        pytest.skip("port 8000 is busy; another service is running")

    blocker = subprocess.Popen(
        ["python", "-m", "http.server", str(PORT), "--bind", "127.0.0.1"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    import time

    time.sleep(1.5)
    try:
        result = _run_script()
        assert result.returncode != 0
        assert "FAIL" in result.stdout
    finally:
        blocker.terminate()
        blocker.wait(timeout=10)
