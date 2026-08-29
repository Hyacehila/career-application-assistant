"""Loopback-only test server for the simulated recruitment browser flow."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = REPOSITORY_ROOT / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from backend.app import create_app, init_database  # noqa: E402
from backend.config import Paths  # noqa: E402

FIXTURE_PATH = Path(__file__).with_name("mock_recruitment.html")


def _test_database_path(value: str) -> Path:
    """Accept only an applications.sqlite file inside our system-temp fixture."""

    candidate = Path(value).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        candidate.relative_to(temp_root)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("E2E database must stay inside system temp.") from exc
    if not candidate.parent.name.startswith("career-board-e2e-"):
        raise argparse.ArgumentTypeError("E2E database directory has an unexpected name.")
    if candidate.name != "applications.sqlite":
        raise argparse.ArgumentTypeError("E2E database filename must be applications.sqlite.")
    return candidate


def build_test_app(database_path: Path) -> FastAPI:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    paths = Paths(repository_root=REPOSITORY_ROOT, private_root=database_path.parent)
    init_database(paths)

    board_app = create_app(db_path=database_path)
    fixture_app = FastAPI(title="Career Board Browser E2E Fixture")

    @fixture_app.get("/mock-recruitment", response_class=HTMLResponse)
    def mock_recruitment() -> str:
        return FIXTURE_PATH.read_text(encoding="utf-8")

    fixture_app.mount("/", board_app)
    return fixture_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=_test_database_path)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")

    uvicorn.run(
        build_test_app(args.database),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
