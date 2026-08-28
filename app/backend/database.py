"""Short-lived SQLite connections with the fixed local database path."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .config import Paths

BUSY_TIMEOUT_MS = 5000


class DatabaseUnavailableError(Exception):
    """Raised when the private overlay or its database cannot be used."""


def open_connection(paths: Paths) -> sqlite3.Connection:
    """Open the fixed database, creating it only in the allowed location."""

    if not paths.private_root.is_dir():
        raise DatabaseUnavailableError(
            "The private/ overlay is missing. "
            "Run scripts/Initialize-PrivateOverlay.ps1 first."
        )

    database_path = paths.database_path
    if not database_path.exists():
        database_path.parent.mkdir(parents=True, exist_ok=True)
        database_path.touch()

    connection = sqlite3.connect(str(database_path), timeout=BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def transaction(paths: Paths):
    """Context manager that yields a connection and commits or rolls back."""

    connection = open_connection(paths)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
