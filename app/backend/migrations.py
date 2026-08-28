"""Idempotent schema migrations for the fixed local board database."""

from __future__ import annotations

import sqlite3

SUPPORTED_SCHEMA_VERSION = 1

MIGRATIONS: dict[int, str] = {
    1: """
CREATE TABLE applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    job_title TEXT NOT NULL,
    department TEXT,
    job_code TEXT,
    application_type TEXT,
    location TEXT,
    source TEXT,
    job_url TEXT,
    current_status TEXT NOT NULL
        CHECK (current_status IN (
            'pending_review', 'applied', 'assessment',
            'interview_1', 'interview_2', 'interview_3', 'interview_hr',
            'offer', 'rejected', 'withdrawn'
        )),
    filled_at TEXT,
    submitted_at TEXT,
    next_action TEXT,
    next_action_date TEXT,
    notes TEXT CHECK (notes IS NULL OR length(notes) <= 1000),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications (id) ON DELETE CASCADE,
    stage TEXT NOT NULL
        CHECK (stage IN (
            'pending_review', 'applied', 'assessment',
            'interview_1', 'interview_2', 'interview_3', 'interview_hr',
            'offer', 'rejected', 'withdrawn'
        )),
    event_date TEXT NOT NULL,
    scheduled_date TEXT,
    scheduled_time TEXT,
    deadline_date TEXT,
    deadline_time TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    mode TEXT,
    location TEXT,
    note TEXT CHECK (note IS NULL OR length(note) <= 500),
    source TEXT NOT NULL
        CHECK (source IN ('agent_fill', 'user_confirmation', 'email_extract', 'manual_ui')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (application_id, stage, event_date, scheduled_date, scheduled_time, deadline_date, deadline_time)
);

CREATE INDEX idx_applications_lookup
    ON applications (company_name, job_title);
CREATE INDEX idx_applications_archived
    ON applications (archived_at);
CREATE INDEX idx_events_application
    ON application_events (application_id, created_at);
"""
}


class SchemaVersionError(Exception):
    """Raised when the database schema version is unknown or incompatible."""


def ensure_migrations(connection: sqlite3.Connection) -> int:
    """Apply pending migrations and return the resulting schema version."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
        """
    )
    row = connection.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()
    current = int(row["version"] or 0)
    if current > SUPPORTED_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Database schema version {current} is newer than supported "
            f"version {SUPPORTED_SCHEMA_VERSION}; refusing to start."
        )

    from datetime import datetime, timezone

    for version in range(current + 1, SUPPORTED_SCHEMA_VERSION + 1):
        connection.executescript(MIGRATIONS[version])
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, datetime.now(timezone.utc).isoformat()),
        )
    return current


def get_schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["version"] or 0)
