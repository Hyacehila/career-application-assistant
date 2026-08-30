"""PowerShell entry-point contracts exercised only against synthetic fixtures."""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PWSH = shutil.which("pwsh")


def _run_script(script: Path, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    if PWSH is None:
        pytest.skip("pwsh is required")
    return subprocess.run(
        [PWSH, "-NoProfile", "-File", str(script), *arguments],
        cwd=cwd or script.parent.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )


def _initializer_fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "public-repository"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "Initialize-PrivateOverlay.ps1"
    shutil.copy2(REPOSITORY_ROOT / "scripts" / script.name, script)
    (root / "resume_materials.example.md").write_text("# Public placeholder\n", encoding="utf-8")
    return root, script


def test_private_overlay_initializer_is_safe_and_idempotent(tmp_path: Path) -> None:
    root, script = _initializer_fixture(tmp_path)
    private_root = root / "private"
    private_root.mkdir()
    unrelated = private_root / "keep-me.txt"
    unrelated.write_text("synthetic marker", encoding="utf-8")

    first = _run_script(script, cwd=root)
    assert first.returncode == 0, first.stdout + first.stderr
    materials = private_root / "resume_materials.md"
    assert materials.read_text(encoding="utf-8") == "# Public placeholder\n"
    assert unrelated.read_text(encoding="utf-8") == "synthetic marker"

    materials.write_text("synthetic existing materials", encoding="utf-8")
    (root / "resume_materials.example.md").write_text("changed template", encoding="utf-8")
    second = _run_script(script, cwd=root)
    assert second.returncode == 0, second.stdout + second.stderr
    assert materials.read_text(encoding="utf-8") == "synthetic existing materials"
    assert "was not read or changed" in second.stdout
    assert unrelated.read_text(encoding="utf-8") == "synthetic marker"


@pytest.mark.parametrize("conflict", ["private", "materials"])
def test_private_overlay_initializer_rejects_conflicting_paths(
    tmp_path: Path, conflict: str
) -> None:
    root, script = _initializer_fixture(tmp_path)
    if conflict == "private":
        (root / "private").write_text("synthetic conflict", encoding="utf-8")
    else:
        (root / "private" / "resume_materials.md").mkdir(parents=True)

    result = _run_script(script, cwd=root)
    assert result.returncode != 0


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


@contextmanager
def _synthetic_health_server(*, demo_identity: bool):
    class Handler(BaseHTTPRequestHandler):
        reset_bodies: list[bytes] = []

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/api/health":
                self.send_error(404)
                return
            body = {
                "status": "ok",
                "database": "available",
                "schema_version": 3,
                "service": (
                    "career-application-assistant" if demo_identity else "unknown-service"
                ),
                "mode": "demo" if demo_identity else "unknown",
                "synthetic_data": demo_identity,
                "mail_ingestion": False,
            }
            payload = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.__class__.reset_bodies.append(self.rfile.read(length))
            payload = b'{"ok":true,"records_seeded":6}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 8001), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_demo_script_is_idempotent_and_reset_uses_empty_json() -> None:
    if not _port_is_free(8001):
        pytest.skip("port 8001 is busy")
    script = REPOSITORY_ROOT / "scripts" / "Start-Demo.ps1"
    with _synthetic_health_server(demo_identity=True) as handler:
        ordinary = _run_script(script)
        reset = _run_script(script, "-Reset")

    assert ordinary.returncode == 0, ordinary.stdout + ordinary.stderr
    assert "already running" in ordinary.stdout
    assert reset.returncode == 0, reset.stdout + reset.stderr
    assert handler.reset_bodies == [b"{}"]


def test_demo_script_fails_closed_when_unknown_service_owns_port() -> None:
    if not _port_is_free(8001):
        pytest.skip("port 8001 is busy")
    script = REPOSITORY_ROOT / "scripts" / "Start-Demo.ps1"
    with _synthetic_health_server(demo_identity=False):
        result = _run_script(script)

    assert result.returncode != 0
    assert "unknown service" in result.stdout


def test_public_release_policy_self_test_is_index_independent() -> None:
    script = REPOSITORY_ROOT / "scripts" / "Test-PublicRelease.ps1"
    result = _run_script(script, "-PolicySelfTest")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "RESULT: PASS" in result.stdout


@pytest.mark.parametrize("mode", ["Standard", "Demo"])
def test_environment_output_is_fixed_and_redacted(tmp_path: Path, mode: str) -> None:
    root = tmp_path / "public-repository"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "Test-Environment.ps1"
    shutil.copy2(REPOSITORY_ROOT / "scripts" / script.name, script)

    result = _run_script(script, "-Mode", mode, cwd=root)
    combined_output = result.stdout + result.stderr
    output_lines = [line for line in combined_output.splitlines() if line]
    assert output_lines
    assert all(
        line.startswith(("PASS: ", "FAIL: ", "RESULT: PASS", "RESULT: FAIL"))
        for line in output_lines
    )
    assert all(":" not in line.partition(": ")[2] for line in output_lines if ": " in line)
    lowered = combined_output.casefold()
    forbidden_fragments = {
        "resume_materials",
        "credential",
        "attachment",
        str(root).casefold(),
        str(REPOSITORY_ROOT).casefold(),
        str(Path.home()).casefold(),
        Path.home().name.casefold(),
    }
    assert all(fragment not in lowered for fragment in forbidden_fragments if fragment)
    assert re.search(r"(?i)(?:[a-z]:[\\/]|/users/|/home/)", combined_output) is None
