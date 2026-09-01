"""Idempotent schema migrations for the fixed local board database."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

SUPPORTED_SCHEMA_VERSION = 4

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
""",
    2: """
CREATE TABLE mail_accounts (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL UNIQUE
        CHECK (provider IN ('outlook', 'qq', '163')),
    status TEXT NOT NULL
        CHECK (status IN (
            'disconnected', 'connecting', 'connected', 'paused',
            'needs_reauth', 'error'
        )),
    public_client_id TEXT,
    history_window TEXT NOT NULL DEFAULT 'new_only'
        CHECK (history_window IN ('new_only', 'last_30_days', 'last_90_days')),
    last_attempt_at TEXT,
    last_success_at TEXT,
    next_retry_at TEXT,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    disconnected_at TEXT
);

CREATE TABLE mail_sync_cursors (
    account_id TEXT PRIMARY KEY
        REFERENCES mail_accounts (id) ON DELETE CASCADE,
    folder_key TEXT NOT NULL DEFAULT 'inbox'
        CHECK (folder_key = 'inbox'),
    graph_delta_link TEXT,
    imap_uidvalidity INTEGER,
    imap_last_uid INTEGER,
    initial_cutoff_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE mail_event_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL
        REFERENCES mail_accounts (id) ON DELETE RESTRICT,
    fingerprint TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL
        CHECK (state IN ('pending', 'committed', 'dismissed', 'expired', 'duplicate')),
    commit_mode TEXT
        CHECK (commit_mode IS NULL OR commit_mode IN ('auto', 'manual')),
    company_name TEXT,
    job_title TEXT,
    proposed_stage TEXT
        CHECK (proposed_stage IS NULL OR proposed_stage IN (
            'applied', 'assessment', 'interview_1', 'interview_2',
            'interview_3', 'interview_hr', 'interview_unspecified',
            'offer', 'rejected', 'withdrawn'
        )),
    event_date TEXT,
    scheduled_date TEXT,
    scheduled_time TEXT,
    deadline_date TEXT,
    deadline_time TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    confidence INTEGER NOT NULL DEFAULT 0
        CHECK (confidence BETWEEN 0 AND 100),
    matched_application_id INTEGER
        REFERENCES applications (id) ON DELETE SET NULL,
    application_event_id INTEGER UNIQUE
        REFERENCES application_events (id) ON DELETE SET NULL,
    review_reasons TEXT NOT NULL DEFAULT '[]',
    expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_mail_accounts_status
    ON mail_accounts (status, provider);
CREATE INDEX idx_mail_candidates_queue
    ON mail_event_candidates (state, expires_at, created_at);
CREATE INDEX idx_mail_candidates_account
    ON mail_event_candidates (account_id, created_at);
""",
    3: """
ALTER TABLE mail_accounts ADD COLUMN connection_generation TEXT NOT NULL DEFAULT '';
ALTER TABLE mail_accounts ADD COLUMN credential_ref TEXT;
ALTER TABLE mail_accounts ADD COLUMN pending_credential_ref TEXT;
ALTER TABLE mail_accounts ADD COLUMN previous_credential_ref TEXT;

UPDATE mail_accounts
SET connection_generation = id,
    credential_ref = id
WHERE connection_generation = '';

CREATE INDEX idx_mail_accounts_credential_cleanup
    ON mail_accounts (provider, pending_credential_ref, previous_credential_ref);
""",
    4: """
ALTER TABLE application_events ADD COLUMN completed_date TEXT;
"""
}


class SchemaVersionError(Exception):
    """Raised when the database schema version is unknown or incompatible."""


def _apply_migration(connection: sqlite3.Connection, version: int) -> None:
    """Apply and record one migration in a recoverable SQLite transaction."""

    try:
        connection.executescript(f"BEGIN IMMEDIATE;\n{MIGRATIONS[version]}")
        connection.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (version, datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


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

    for version in range(current + 1, SUPPORTED_SCHEMA_VERSION + 1):
        _apply_migration(connection, version)
    return SUPPORTED_SCHEMA_VERSION


def get_schema_version(connection: sqlite3.Connection) -> int:
    try:
        row = connection.execute("SELECT max(version) AS version FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return 0
    return int(row["version"] or 0)
