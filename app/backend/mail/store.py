"""Persistence and safety policy for structured mailbox ingestion."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Mapping

from .. import store as application_store
from ..clock import CN_TZ, now_iso
from ..errors import ApiError, not_found, stage_conflict, validation_error
from ..matching import MatchQuery, find_matching
from ..schemas import CreateEvent
from .classifier import contains_private_contact_info
from .schemas import MailCandidateConfirmRequest, MailCandidateOut

PROVIDERS = ("outlook", "qq", "163")
AUTO_STAGES = {
    "assessment",
    "interview_1",
    "interview_2",
    "interview_3",
    "interview_hr",
}
FINISHED_STAGES = {"offer", "rejected", "withdrawn"}
AUTO_TRANSITIONS = {
    "pending_review": AUTO_STAGES,
    "applied": AUTO_STAGES,
    "assessment": {"interview_1", "interview_2", "interview_3", "interview_hr"},
    "interview_1": {"interview_2", "interview_3", "interview_hr"},
    "interview_2": {"interview_3", "interview_hr"},
    "interview_3": {"interview_hr"},
    "interview_hr": set(),
    "offer": set(),
    "rejected": set(),
    "withdrawn": set(),
}
AUTO_BLOCKING_REASONS = {
    "ambiguous_date",
    "conflicting_dates",
    "conflicting_stages",
    "body_too_large",
    "body_missing",
    "generic_interview",
    "low_confidence",
    "quoted_only_signal",
}
REASON_RE = re.compile(r"^[a-z0-9_]{1,80}$")


def _clean_text(value: object, limit: int = 200) -> str | None:
    if value is None:
        return None
    candidate = " ".join(str(value).split()).strip()
    if not candidate:
        return None
    return candidate[:limit]


def _clean_candidate_label(value: object) -> str | None:
    candidate = _clean_text(value)
    if candidate is None or contains_private_contact_info(candidate):
        return None
    return candidate


def _clean_reasons(values: object) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    result: list[str] = []
    for value in values:
        candidate = str(value).strip().casefold()
        if REASON_RE.match(candidate) and candidate not in result:
            result.append(candidate)
        if len(result) >= 20:
            break
    return result


def _review_reasons(values: object) -> list[str]:
    """Keep only actionable machine reason codes, never positive score labels."""

    aliases = {
        "charset_fallback": "encoding_fallback",
        "job_digest_signal": "job_alert",
    }
    allowed = {
        "ambiguous_date",
        "archived_application",
        "body_missing",
        "body_too_large",
        "conflicting_dates",
        "conflicting_stages",
        "encoding_fallback",
        "generic_interview",
        "job_alert",
        "quoted_only_signal",
    }
    result: list[str] = []
    for reason in _clean_reasons(values):
        normalized = aliases.get(reason, reason)
        if normalized in allowed and normalized not in result:
            result.append(normalized)
    return result


def _iso_after_days(days: int) -> str:
    return (datetime.now(CN_TZ) + timedelta(days=days)).isoformat(timespec="milliseconds")


def ensure_account(connection: sqlite3.Connection, provider: str) -> dict:
    if provider not in PROVIDERS:
        raise validation_error("Unknown mail provider.")
    row = connection.execute(
        "SELECT * FROM mail_accounts WHERE provider = ?", (provider,)
    ).fetchone()
    if row is not None:
        return dict(row)
    timestamp = now_iso()
    account_id = str(uuid.uuid4())
    connection_generation = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO mail_accounts (
            id, provider, status, public_client_id, history_window,
            last_attempt_at, last_success_at, next_retry_at, last_error_code,
            created_at, updated_at, disconnected_at, connection_generation,
            credential_ref, pending_credential_ref, previous_credential_ref
        ) VALUES (?, ?, 'disconnected', NULL, 'new_only', NULL, NULL, NULL, NULL,
                  ?, ?, ?, ?, NULL, NULL, NULL)
        """,
        (
            account_id,
            provider,
            timestamp,
            timestamp,
            timestamp,
            connection_generation,
        ),
    )
    return dict(
        connection.execute("SELECT * FROM mail_accounts WHERE id = ?", (account_id,)).fetchone()
    )


def get_account(connection: sqlite3.Connection, provider: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM mail_accounts WHERE provider = ?", (provider,)
    ).fetchone()
    return dict(row) if row is not None else None


def list_account_rows(connection: sqlite3.Connection) -> list[dict]:
    rows = {
        row["provider"]: dict(row)
        for row in connection.execute("SELECT * FROM mail_accounts").fetchall()
    }
    counts = {
        row["provider"]: int(row["pending_count"])
        for row in connection.execute(
            """
            SELECT a.provider, count(c.id) AS pending_count
            FROM mail_accounts a
            LEFT JOIN mail_event_candidates c
              ON c.account_id = a.id AND c.state = 'pending'
            GROUP BY a.provider
            """
        ).fetchall()
    }
    result: list[dict] = []
    for provider in PROVIDERS:
        row = rows.get(provider)
        if row is None:
            result.append(
                {
                    "provider": provider,
                    "status": "disconnected",
                    "history_window": "new_only",
                    "last_attempt_at": None,
                    "last_success_at": None,
                    "next_retry_at": None,
                    "last_error_code": None,
                    "pending_count": 0,
                }
            )
        else:
            row["pending_count"] = counts.get(provider, 0)
            result.append(row)
    return result


def update_account(
    connection: sqlite3.Connection,
    provider: str,
    *,
    status: str,
    history_window: str | None = None,
    public_client_id: str | None | object = ...,
    error_code: str | None | object = ...,
    last_attempt: bool = False,
    last_success: bool = False,
    next_retry_at: str | None | object = ...,
    connection_generation: str | object = ...,
    credential_ref: str | None | object = ...,
    pending_credential_ref: str | None | object = ...,
    previous_credential_ref: str | None | object = ...,
) -> dict:
    account = ensure_account(connection, provider)
    fields: dict[str, object] = {"status": status, "updated_at": now_iso()}
    if history_window is not None:
        fields["history_window"] = history_window
    if public_client_id is not ...:
        fields["public_client_id"] = public_client_id
    if error_code is not ...:
        fields["last_error_code"] = error_code
    if last_attempt:
        fields["last_attempt_at"] = now_iso()
    if last_success:
        fields["last_success_at"] = now_iso()
    if next_retry_at is not ...:
        fields["next_retry_at"] = next_retry_at
    if connection_generation is not ...:
        fields["connection_generation"] = connection_generation
    if credential_ref is not ...:
        fields["credential_ref"] = credential_ref
    if pending_credential_ref is not ...:
        fields["pending_credential_ref"] = pending_credential_ref
    if previous_credential_ref is not ...:
        fields["previous_credential_ref"] = previous_credential_ref
    if status == "disconnected":
        fields["disconnected_at"] = now_iso()
    elif status in {"connected", "paused"}:
        fields["disconnected_at"] = None
    assignments = ", ".join(f"{key} = ?" for key in fields)
    connection.execute(
        f"UPDATE mail_accounts SET {assignments} WHERE id = ?",
        [*fields.values(), account["id"]],
    )
    return dict(
        connection.execute("SELECT * FROM mail_accounts WHERE id = ?", (account["id"],)).fetchone()
    )


def disconnect_account(connection: sqlite3.Connection, provider: str) -> dict:
    account = ensure_account(connection, provider)
    connection.execute("DELETE FROM mail_sync_cursors WHERE account_id = ?", (account["id"],))
    return update_account(
        connection,
        provider,
        status="disconnected",
        public_client_id=None,
        error_code=None,
        next_retry_at=None,
        credential_ref=None,
        pending_credential_ref=None,
        previous_credential_ref=None,
    )


def get_cursor(connection: sqlite3.Connection, account_id: str) -> dict | None:
    row = connection.execute(
        "SELECT * FROM mail_sync_cursors WHERE account_id = ?", (account_id,)
    ).fetchone()
    return dict(row) if row is not None else None


def save_graph_cursor(
    connection: sqlite3.Connection,
    account_id: str,
    delta_link: str,
    initial_cutoff_at: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO mail_sync_cursors (
            account_id, folder_key, graph_delta_link, imap_uidvalidity,
            imap_last_uid, initial_cutoff_at, updated_at
        ) VALUES (?, 'inbox', ?, NULL, NULL, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            graph_delta_link = excluded.graph_delta_link,
            imap_uidvalidity = NULL,
            imap_last_uid = NULL,
            initial_cutoff_at = excluded.initial_cutoff_at,
            updated_at = excluded.updated_at
        """,
        (account_id, delta_link, initial_cutoff_at, now_iso()),
    )


def save_imap_cursor(
    connection: sqlite3.Connection,
    account_id: str,
    uidvalidity: int,
    last_uid: int,
    initial_cutoff_at: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO mail_sync_cursors (
            account_id, folder_key, graph_delta_link, imap_uidvalidity,
            imap_last_uid, initial_cutoff_at, updated_at
        ) VALUES (?, 'inbox', NULL, ?, ?, ?, ?)
        ON CONFLICT(account_id) DO UPDATE SET
            graph_delta_link = NULL,
            imap_uidvalidity = excluded.imap_uidvalidity,
            imap_last_uid = excluded.imap_last_uid,
            initial_cutoff_at = excluded.initial_cutoff_at,
            updated_at = excluded.updated_at
        """,
        (account_id, uidvalidity, last_uid, initial_cutoff_at, now_iso()),
    )


def message_fingerprint(account_id: str, provider: str, source_key: str) -> str:
    material = f"{account_id}\0{provider}\0inbox\0{source_key}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _candidate_from_row(row: sqlite3.Row | Mapping[str, Any]) -> MailCandidateOut:
    values = dict(row)
    reasons = values.get("review_reasons")
    if isinstance(reasons, str):
        try:
            reasons = json.loads(reasons)
        except (TypeError, json.JSONDecodeError):
            reasons = []
    return MailCandidateOut(
        id=values["id"],
        provider=values["provider"],
        state=values["state"],
        company_name=values.get("company_name"),
        job_title=values.get("job_title"),
        proposed_stage=values.get("proposed_stage"),
        event_date=values.get("event_date"),
        scheduled_date=values.get("scheduled_date"),
        scheduled_time=values.get("scheduled_time"),
        deadline_date=values.get("deadline_date"),
        deadline_time=values.get("deadline_time"),
        timezone=values.get("timezone") or "Asia/Shanghai",
        confidence=values.get("confidence") or 0,
        matched_application_id=values.get("matched_application_id"),
        review_reasons=_clean_reasons(reasons),
        expires_at=values.get("expires_at"),
    )


def get_candidate(connection: sqlite3.Connection, candidate_id: int) -> MailCandidateOut:
    row = connection.execute(
        """
        SELECT c.*, a.provider
        FROM mail_event_candidates c
        JOIN mail_accounts a ON a.id = c.account_id
        WHERE c.id = ?
        """,
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "mail_candidate_not_found", "Mail candidate not found.")
    return _candidate_from_row(row)


def list_candidates(
    connection: sqlite3.Connection, state: str = "pending", limit: int = 100
) -> tuple[list[MailCandidateOut], int]:
    expire_pending_candidates(connection)
    total = int(
        connection.execute(
            "SELECT count(*) FROM mail_event_candidates WHERE state = ?", (state,)
        ).fetchone()[0]
    )
    rows = connection.execute(
        """
        SELECT c.*, a.provider
        FROM mail_event_candidates c
        JOIN mail_accounts a ON a.id = c.account_id
        WHERE c.state = ?
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ?
        """,
        (state, limit),
    ).fetchall()
    return [_candidate_from_row(row) for row in rows], total


def expire_pending_candidates(connection: sqlite3.Connection) -> int:
    cursor = connection.execute(
        """
        UPDATE mail_event_candidates
        SET state = 'expired', commit_mode = NULL,
            company_name = NULL, job_title = NULL, proposed_stage = NULL,
            event_date = NULL, scheduled_date = NULL, scheduled_time = NULL,
            deadline_date = NULL, deadline_time = NULL,
            matched_application_id = NULL, review_reasons = '[]', updated_at = ?
        WHERE state = 'pending' AND expires_at IS NOT NULL AND expires_at <= ?
        """,
        (now_iso(), now_iso()),
    )
    return cursor.rowcount


def _match_and_strength(connection: sqlite3.Connection, extracted: Mapping[str, Any]) -> tuple[list[dict], int]:
    query = MatchQuery(
        application_id=extracted.get("application_id"),
        company_name=_clean_candidate_label(extracted.get("company_name")),
        job_title=_clean_candidate_label(extracted.get("job_title")),
        job_code=_clean_text(extracted.get("job_code")),
        location=_clean_text(extracted.get("location")),
        job_url=_clean_text(extracted.get("job_url"), 2000),
    )
    matches = find_matching(connection, query) if query.has_any() else []
    if query.application_id is not None or query.job_url or (query.company_name and query.job_code):
        strength = 35
    elif query.company_name and query.job_title and query.location:
        strength = 30
    else:
        strength = 0
    return matches, strength if len(matches) == 1 else 0


def _required_date_present(stage: str, extracted: Mapping[str, Any]) -> bool:
    if stage == "assessment":
        return bool(extracted.get("scheduled_date") or extracted.get("deadline_date"))
    if stage.startswith("interview_") and stage != "interview_unspecified":
        return bool(extracted.get("scheduled_date"))
    return True


def calculate_confidence(
    stage: str,
    extracted: Mapping[str, Any],
    match_strength: int,
    reasons: list[str],
) -> int:
    score = 20 if stage == "interview_unspecified" else 35
    score += match_strength
    if _required_date_present(stage, extracted):
        score += 20
    if not set(reasons).intersection(
        {"ambiguous_date", "conflicting_dates", "conflicting_stages", "quoted_only_signal"}
    ):
        score += 10
    penalties = {
        "conflicting_dates": 30,
        "conflicting_stages": 30,
        "ambiguous_date": 30,
        "encoding_fallback": 15,
        "quoted_only_signal": 15,
        "body_too_large": 30,
        "job_alert": 40,
    }
    score -= sum(penalties.get(reason, 0) for reason in set(reasons))
    return max(0, min(100, score))


def _existing_event(connection: sqlite3.Connection, application_id: int, event: CreateEvent):
    return connection.execute(
        """
        SELECT * FROM application_events
        WHERE application_id = ? AND stage = ? AND event_date = ?
          AND scheduled_date IS ? AND scheduled_time IS ?
          AND deadline_date IS ? AND deadline_time IS ?
        """,
        (
            application_id,
            event.stage,
            event.event_date,
            event.scheduled_date,
            event.scheduled_time,
            event.deadline_date,
            event.deadline_time,
        ),
    ).fetchone()


def _auto_reasons(
    record: dict | None,
    stage: str,
    extracted: Mapping[str, Any],
    confidence: int,
    reasons: list[str],
) -> list[str]:
    result = list(reasons)
    if record is None:
        result.append("missing_match")
    if stage not in AUTO_STAGES:
        result.append("manual_stage")
    if stage == "interview_unspecified":
        result.append("generic_interview")
    if not _required_date_present(stage, extracted):
        result.append("missing_required_date")
    if confidence < 90:
        result.append("low_confidence")
    if record is not None:
        if record.get("archived_at") is not None:
            result.append("archived_application")
        allowed = AUTO_TRANSITIONS.get(record["current_status"], set())
        if stage not in allowed:
            result.append("unsafe_transition")
    return list(dict.fromkeys(result))


def create_candidate(
    connection: sqlite3.Connection,
    *,
    account_id: str,
    provider: str,
    source_key: str,
    extracted: Mapping[str, Any],
) -> tuple[MailCandidateOut | None, dict | None, dict | None]:
    """Persist one structured extraction and auto-commit only when all gates pass.

    Returns ``(candidate, application, event)``. A missing/unclear stage returns
    ``(None, None, None)`` and never stores content.
    """

    stage = str(extracted.get("proposed_stage") or "").strip()
    if stage not in {
        "applied",
        "assessment",
        "interview_1",
        "interview_2",
        "interview_3",
        "interview_hr",
        "interview_unspecified",
        "offer",
        "rejected",
        "withdrawn",
    }:
        return None, None, None
    event_date = _clean_text(extracted.get("event_date"), 10)
    if event_date is None:
        return None, None, None
    fingerprint = message_fingerprint(account_id, provider, source_key)
    existing_row = connection.execute(
        """
        SELECT c.*, a.provider
        FROM mail_event_candidates c JOIN mail_accounts a ON a.id = c.account_id
        WHERE c.fingerprint = ?
        """,
        (fingerprint,),
    ).fetchone()
    if existing_row is not None:
        return _candidate_from_row(existing_row), None, None

    matches, match_strength = _match_and_strength(connection, extracted)
    reasons = _review_reasons(extracted.get("review_reasons"))
    if len(matches) > 1:
        reasons.append("multiple_matches")
    record = matches[0] if len(matches) == 1 else None
    confidence = calculate_confidence(stage, extracted, match_strength, reasons)
    reasons = _auto_reasons(record, stage, extracted, confidence, reasons)
    timestamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO mail_event_candidates (
            account_id, fingerprint, state, commit_mode, company_name, job_title,
            proposed_stage, event_date, scheduled_date, scheduled_time,
            deadline_date, deadline_time, timezone, confidence,
            matched_application_id, application_event_id, review_reasons,
            expires_at, created_at, updated_at
        ) VALUES (?, ?, 'pending', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            account_id,
            fingerprint,
            _clean_candidate_label(extracted.get("company_name")),
            _clean_candidate_label(extracted.get("job_title")),
            stage,
            event_date,
            _clean_text(extracted.get("scheduled_date"), 10),
            _clean_text(extracted.get("scheduled_time"), 5),
            _clean_text(extracted.get("deadline_date"), 10),
            _clean_text(extracted.get("deadline_time"), 5),
            _clean_text(extracted.get("timezone"), 100) or "Asia/Shanghai",
            confidence,
            record["id"] if record else None,
            json.dumps(list(dict.fromkeys(reasons)), separators=(",", ":")),
            _iso_after_days(90),
            timestamp,
            timestamp,
        ),
    )
    candidate_id = int(cursor.lastrowid)

    hard_blocked = bool(set(reasons).intersection(AUTO_BLOCKING_REASONS))
    if record and not reasons and not hard_blocked:
        event_payload = CreateEvent(
            stage=stage,
            event_date=event_date,
            scheduled_date=_clean_text(extracted.get("scheduled_date"), 10),
            scheduled_time=_clean_text(extracted.get("scheduled_time"), 5),
            deadline_date=_clean_text(extracted.get("deadline_date"), 10),
            deadline_time=_clean_text(extracted.get("deadline_time"), 5),
            timezone=_clean_text(extracted.get("timezone"), 100) or "Asia/Shanghai",
            source="email_extract",
        )
        duplicate = _existing_event(connection, record["id"], event_payload)
        if duplicate is not None:
            connection.execute(
                """
                UPDATE mail_event_candidates
                SET state = 'duplicate', application_event_id = ?,
                    company_name = NULL, job_title = NULL, proposed_stage = NULL,
                    event_date = NULL, scheduled_date = NULL, scheduled_time = NULL,
                    deadline_date = NULL, deadline_time = NULL,
                    review_reasons = '[]', updated_at = ?
                WHERE id = ?
                """,
                (duplicate["id"], now_iso(), candidate_id),
            )
            return get_candidate(connection, candidate_id), record, dict(duplicate)
        updated, event = application_store.add_event(connection, record["id"], event_payload)
        connection.execute(
            """
            UPDATE mail_event_candidates
            SET state = 'committed', commit_mode = 'auto', application_event_id = ?,
                company_name = NULL, job_title = NULL, proposed_stage = NULL,
                event_date = NULL, scheduled_date = NULL, scheduled_time = NULL,
                deadline_date = NULL, deadline_time = NULL,
                review_reasons = '[]', updated_at = ?
            WHERE id = ?
            """,
            (event.id, now_iso(), candidate_id),
        )
        return get_candidate(connection, candidate_id), updated.model_dump(), event.model_dump()
    return get_candidate(connection, candidate_id), record, None


def confirm_candidate(
    connection: sqlite3.Connection,
    candidate_id: int,
    payload: MailCandidateConfirmRequest,
) -> tuple[MailCandidateOut, dict, dict]:
    row = connection.execute(
        "SELECT * FROM mail_event_candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    if row is None:
        raise ApiError(404, "mail_candidate_not_found", "Mail candidate not found.")
    values = dict(row)
    if values["state"] != "pending":
        raise stage_conflict("This mail candidate is no longer pending review.")
    if not values.get("event_date"):
        raise validation_error("The mail candidate no longer contains an event date.")

    source = "user_confirmation" if payload.stage == "applied" else "email_extract"
    event_payload = CreateEvent(
        stage=payload.stage,
        event_date=values["event_date"],
        scheduled_date=payload.scheduled_date,
        scheduled_time=payload.scheduled_time,
        deadline_date=payload.deadline_date,
        deadline_time=payload.deadline_time,
        timezone=payload.timezone,
        source=source,
    )
    event_payload.validate_stage_rules()
    record, event = application_store.add_event(
        connection, payload.application_id, event_payload
    )
    connection.execute(
        """
        UPDATE mail_event_candidates
        SET state = 'committed', commit_mode = 'manual',
            matched_application_id = ?, application_event_id = ?,
            company_name = NULL, job_title = NULL, proposed_stage = NULL,
            event_date = NULL, scheduled_date = NULL, scheduled_time = NULL,
            deadline_date = NULL, deadline_time = NULL,
            review_reasons = '[]', updated_at = ?
        WHERE id = ?
        """,
        (payload.application_id, event.id, now_iso(), candidate_id),
    )
    return get_candidate(connection, candidate_id), record.model_dump(), event.model_dump()


def dismiss_candidate(connection: sqlite3.Connection, candidate_id: int) -> None:
    row = connection.execute(
        "SELECT state FROM mail_event_candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    if row is None:
        raise ApiError(404, "mail_candidate_not_found", "Mail candidate not found.")
    if row["state"] == "committed":
        raise stage_conflict("A committed mail candidate cannot be dismissed.")
    if row["state"] in {"dismissed", "expired"}:
        return
    connection.execute(
        """
        UPDATE mail_event_candidates
        SET state = 'dismissed', commit_mode = NULL,
            company_name = NULL, job_title = NULL, proposed_stage = NULL,
            event_date = NULL, scheduled_date = NULL, scheduled_time = NULL,
            deadline_date = NULL, deadline_time = NULL,
            matched_application_id = NULL, review_reasons = '[]', updated_at = ?
        WHERE id = ?
        """,
        (now_iso(), candidate_id),
    )
