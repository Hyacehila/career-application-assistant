"""Pytest fixtures: temporary private overlay and injected test database."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


@pytest.fixture
def private_root(tmp_path: Path) -> Path:
    """A temporary private/ overlay with the required materials file."""

    root = tmp_path / "private"
    root.mkdir()
    (root / "resume_materials.md").write_text("placeholder\n", encoding="utf-8")
    return root


@pytest.fixture
def db_path(private_root: Path) -> Path:
    return private_root / "applications.sqlite"


@pytest.fixture
def app(private_root: Path, db_path: Path):
    from backend.app import create_test_app, init_database
    from backend.config import Paths

    paths = Paths(repository_root=private_root.parent, private_root=private_root)
    init_database(paths)
    return create_test_app(paths)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1:8000") as test_client:
        yield test_client
