"""Run the isolated synthetic Demo on the fixed loopback endpoint."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

APP_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from backend.app import create_demo_app, init_database  # noqa: E402
from backend.config import Paths  # noqa: E402
from backend.demo import cleanup_demo_directory, reset_demo_data, validate_demo_directory  # noqa: E402

DEMO_HOST = "127.0.0.1"
DEMO_PORT = 8001


def create_demo_session_directory() -> Path:
    """Create an unguessable direct child of the operating-system temp root."""

    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    for _ in range(10):
        candidate = temp_root / f"career-application-assistant-demo-{uuid4().hex}"
        try:
            candidate.mkdir(mode=0o700)
        except FileExistsError:  # pragma: no cover - UUID collision defense
            continue
        return validate_demo_directory(candidate)
    raise RuntimeError("Unable to allocate a unique Demo session directory.")


def build_demo_app(session_directory: Path):
    """Initialize and seed one validated Demo session."""

    paths = Paths(repository_root=REPOSITORY_ROOT, private_root=session_directory)
    init_database(paths)
    reset_demo_data(paths)
    return create_demo_app(paths)


def main() -> None:
    if len(sys.argv) != 1:
        raise SystemExit("Demo server does not accept host, port, database, or directory arguments.")

    session_directory = create_demo_session_directory()
    try:
        app = build_demo_app(session_directory)
        import uvicorn

        uvicorn.run(
            app,
            host=DEMO_HOST,
            port=DEMO_PORT,
            log_level="warning",
            access_log=False,
        )
    finally:
        if os.path.lexists(session_directory):
            cleanup_demo_directory(session_directory)


if __name__ == "__main__":
    main()
