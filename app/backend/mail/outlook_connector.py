"""State machine for Outlook mail supplied by the Codex connector.

This module never calls Outlook. It accepts bounded, transient connector data,
applies deterministic parsing, and persists only fingerprints and structured
review candidates.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from ..clock import now_iso
from ..errors import ApiError, validation_error
from . import store
from .classifier import classify_and_extract, is_likely_recruitment_header
from .parsing import MailContentError, html_to_text, trim_quoted_reply
from .schemas import (
    MailAccountOut,
    OutlookBodyTokenOut,
    OutlookHeaderBatchOut,
    OutlookHeaderBatchRequest,
    OutlookMessageBatchOut,
    OutlookMessageBatchRequest,
    OutlookRunCompleteOut,
    OutlookRunCompleteRequest,
    OutlookRunFailOut,
    OutlookRunFailRequest,
    OutlookRunStartOut,
    OutlookScanWindowOut,
)

RUN_BUDGET = 200
RUN_LEASE_MINUTES = 15
INITIAL_HISTORY_DAYS = 30
LIVE_OVERLAP_HOURS = 24


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timestamp must include an offset.")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds")


def ensure_state(connection: sqlite3.Connection) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM outlook_connector_state WHERE singleton_id = 1"
    ).fetchone()
    if row is None:
        timestamp = now_iso()
        connection.execute(
            """
            INSERT OR IGNORE INTO outlook_connector_state (
                singleton_id, status, history_window, created_at, updated_at
            ) VALUES (1, 'disconnected', 'last_30_days', ?, ?)
            """,
            (timestamp, timestamp),
        )
        row = connection.execute(
            "SELECT * FROM outlook_connector_state WHERE singleton_id = 1"
        ).fetchone()
    return dict(row)


def account_out(connection: sqlite3.Connection) -> MailAccountOut:
    state = ensure_state(connection)
    pending = int(
        connection.execute(
            "SELECT count(*) FROM mail_event_candidates WHERE provider = 'outlook' AND state = 'pending'"
        ).fetchone()[0]
    )
    return MailAccountOut(
        provider="outlook",
        connection_mode="codex_connector",
        status=state["status"],
        masked_address=None,
        history_window="last_30_days",
        last_attempt_at=state.get("last_attempt_at"),
        last_success_at=state.get("last_success_at"),
        next_retry_at=None,
        error_code=state.get("last_error_code"),
        pending_count=pending,
    )


def _release_run(connection: sqlite3.Connection, run_id: str) -> None:
    connection.execute(
        """
        UPDATE outlook_scan_windows
        SET leased_by_run_id = NULL, lease_start_index = NULL,
            lease_headers_seen = 0, lease_limit = NULL, updated_at = ?
        WHERE leased_by_run_id = ?
        """,
        (now_iso(), run_id),
    )
    connection.execute(
        "DELETE FROM outlook_connector_body_tokens WHERE run_id = ?", (run_id,)
    )


def _require_active_run(
    connection: sqlite3.Connection, run_id: str, *, now: datetime | None = None
) -> dict[str, Any]:
    state = ensure_state(connection)
    if state.get("active_run_id") != run_id:
        raise ApiError(409, "outlook_run_inactive", "The Outlook connector run is not active.")
    current = (now or _utc_now()).astimezone(UTC)
    lease = state.get("lease_expires_at")
    try:
        active = bool(lease and _as_utc(str(lease)) > current)
    except ValueError:
        active = False
    if not active:
        raise ApiError(409, "outlook_run_expired", "The Outlook connector run lease expired.")
    return state


def _add_window(
    connection: sqlite3.Connection,
    *,
    kind: str,
    start_at: datetime,
    end_at: datetime,
) -> None:
    if start_at >= end_at:
        return
    timestamp = now_iso()
    connection.execute(
        """
        INSERT INTO outlook_scan_windows (
            id, window_kind, start_at, end_at, next_from_index,
            leased_by_run_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 0, NULL, ?, ?)
        ON CONFLICT(window_kind, start_at, end_at) DO NOTHING
        """,
        (str(uuid4()), kind, _iso(start_at), _iso(end_at), timestamp, timestamp),
    )


def start_run(
    connection: sqlite3.Connection, *, now: datetime | None = None
) -> OutlookRunStartOut:
    current = (now or _utc_now()).astimezone(UTC)
    state = ensure_state(connection)
    if state["status"] == "paused":
        return OutlookRunStartOut(state="paused")

    active_run_id = state.get("active_run_id")
    lease = state.get("lease_expires_at")
    if active_run_id and lease:
        try:
            if _as_utc(str(lease)) > current:
                return OutlookRunStartOut(state="busy")
        except ValueError:
            pass
        _release_run(connection, str(active_run_id))

    last_planned = state.get("last_planned_at")
    if last_planned:
        try:
            previous = _as_utc(str(last_planned))
        except ValueError:
            previous = current - timedelta(hours=LIVE_OVERLAP_HOURS)
        _add_window(
            connection,
            kind="live",
            start_at=max(
                previous - timedelta(hours=LIVE_OVERLAP_HOURS),
                current - timedelta(days=INITIAL_HISTORY_DAYS),
            ),
            end_at=current,
        )
    else:
        _add_window(
            connection,
            kind="backfill",
            start_at=current - timedelta(days=INITIAL_HISTORY_DAYS),
            end_at=current,
        )

    newest_live = connection.execute(
        """
        SELECT * FROM outlook_scan_windows
        WHERE leased_by_run_id IS NULL AND window_kind = 'live'
        ORDER BY end_at DESC, created_at ASC
        LIMIT 1
        """
    ).fetchone()
    available = [newest_live] if newest_live is not None else []
    excluded_id = newest_live["id"] if newest_live is not None else ""
    oldest_backlog = connection.execute(
        """
        SELECT * FROM outlook_scan_windows
        WHERE leased_by_run_id IS NULL AND id <> ?
        ORDER BY CASE window_kind WHEN 'backfill' THEN 0 ELSE 1 END,
                 end_at ASC, created_at ASC
        LIMIT 1
        """,
        (excluded_id,),
    ).fetchone()
    if oldest_backlog is not None:
        available.append(oldest_backlog)
    if not available:
        _add_window(
            connection,
            kind="live",
            start_at=current - timedelta(hours=LIVE_OVERLAP_HOURS),
            end_at=current,
        )
        available = list(connection.execute(
            "SELECT * FROM outlook_scan_windows WHERE leased_by_run_id IS NULL ORDER BY end_at DESC LIMIT 1"
        ).fetchall())

    run_id = str(uuid4())
    lease_expires = current + timedelta(minutes=RUN_LEASE_MINUTES)
    limits = [RUN_BUDGET] if len(available) == 1 else [RUN_BUDGET // 2] * 2
    windows: list[OutlookScanWindowOut] = []
    for row, limit in zip(available, limits, strict=True):
        connection.execute(
            """
            UPDATE outlook_scan_windows
            SET leased_by_run_id = ?, lease_start_index = next_from_index,
                lease_headers_seen = 0, lease_limit = ?, updated_at = ?
            WHERE id = ?
            """,
            (run_id, limit, now_iso(), row["id"]),
        )
        windows.append(
            OutlookScanWindowOut(
                id=row["id"],
                kind=row["window_kind"],
                received_from=_as_utc(row["start_at"]),
                received_before=_as_utc(row["end_at"]),
                from_index=int(row["next_from_index"]),
                limit=limit,
            )
        )

    timestamp = now_iso()
    connection.execute(
        """
        UPDATE outlook_connector_state
        SET status = 'connecting', last_planned_at = ?, last_attempt_at = ?,
            last_error_code = NULL, active_run_id = ?, lease_expires_at = ?,
            headers_seen = 0, bodies_seen = 0, updated_at = ?
        WHERE singleton_id = 1
        """,
        (_iso(current), timestamp, run_id, _iso(lease_expires), timestamp),
    )
    return OutlookRunStartOut(
        state="started",
        run_id=run_id,
        lease_expires_at=lease_expires,
        remaining_budget=RUN_BUDGET,
        windows=windows,
    )


def gate_headers(
    connection: sqlite3.Connection,
    run_id: str,
    payload: OutlookHeaderBatchRequest,
) -> OutlookHeaderBatchOut:
    state = _require_active_run(connection, run_id)
    current_count = int(state.get("headers_seen") or 0)
    if current_count + len(payload.items) > RUN_BUDGET:
        raise validation_error("The Outlook connector run exceeded its 200-header budget.")
    window = connection.execute(
        "SELECT * FROM outlook_scan_windows WHERE id = ? AND leased_by_run_id = ?",
        (payload.window_id, run_id),
    ).fetchone()
    if window is None:
        raise validation_error("The Outlook scan window is not leased by this run.")
    expected_from = int(window["lease_start_index"] or 0) + int(
        window["lease_headers_seen"] or 0
    )
    if payload.from_index != expected_from:
        raise validation_error("The Outlook header page is out of sequence.")
    lease_limit = int(window["lease_limit"] or 0)
    window_seen = int(window["lease_headers_seen"] or 0)
    if window_seen + len(payload.items) > lease_limit:
        raise validation_error("The Outlook scan window exceeded its assigned header limit.")

    received_from = _as_utc(window["start_at"])
    received_before = _as_utc(window["end_at"])
    body_tokens: list[OutlookBodyTokenOut] = []
    duplicate_count = 0
    ignored_count = 0
    for item in payload.items:
        received_at = item.received_at.astimezone(UTC)
        if not (received_from <= received_at < received_before):
            raise validation_error("An Outlook header falls outside its assigned scan window.")
        fingerprint = store.message_fingerprint("outlook", item.source_id)
        exists = connection.execute(
            "SELECT 1 FROM mail_event_candidates WHERE fingerprint = ?", (fingerprint,)
        ).fetchone()
        issued = connection.execute(
            """
            SELECT 1 FROM outlook_connector_body_tokens
            WHERE run_id = ? AND fingerprint = ?
            """,
            (run_id, fingerprint),
        ).fetchone()
        if exists is not None or issued is not None:
            duplicate_count += 1
        elif is_likely_recruitment_header(item.subject, item.sender):
            body_token = secrets.token_urlsafe(32)
            connection.execute(
                """
                INSERT INTO outlook_connector_body_tokens (
                    run_id, token_hash, fingerprint, header_hash, consumed, created_at
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    run_id,
                    _digest(body_token),
                    fingerprint,
                    _header_hash(item),
                    now_iso(),
                ),
            )
            body_tokens.append(
                OutlookBodyTokenOut(token=item.token, body_token=body_token)
            )
        else:
            ignored_count += 1
    new_count = current_count + len(payload.items)
    connection.execute(
        "UPDATE outlook_connector_state SET headers_seen = ?, updated_at = ? WHERE singleton_id = 1",
        (new_count, now_iso()),
    )
    connection.execute(
        """
        UPDATE outlook_scan_windows
        SET lease_headers_seen = ?, updated_at = ?
        WHERE id = ? AND leased_by_run_id = ?
        """,
        (window_seen + len(payload.items), now_iso(), payload.window_id, run_id),
    )
    return OutlookHeaderBatchOut(
        body_tokens=body_tokens,
        duplicate_count=duplicate_count,
        ignored_count=ignored_count,
        remaining_budget=RUN_BUDGET - new_count,
    )


def _extraction_mapping(extracted: Any, extra_reasons: list[str]) -> dict[str, Any]:
    return {
        "proposed_stage": extracted.stage,
        "event_date": extracted.event_date,
        "scheduled_date": extracted.scheduled_date,
        "scheduled_time": extracted.scheduled_time,
        "deadline_date": extracted.deadline_date,
        "deadline_time": extracted.deadline_time,
        "timezone": extracted.timezone,
        "company_name": extracted.company_name,
        "job_title": extracted.job_title,
        "job_code": extracted.job_code,
        "job_url": extracted.job_url,
        "location": extracted.location,
        "review_reasons": [*extracted.reasons, *extra_reasons],
    }


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _header_hash(item: Any) -> str:
    material = "\0".join(
        (
            item.token,
            item.source_id,
            item.subject,
            item.sender,
            item.received_at.astimezone(UTC).isoformat(),
        )
    )
    return _digest(material)


def ingest_messages(
    connection: sqlite3.Connection,
    run_id: str,
    payload: OutlookMessageBatchRequest,
) -> OutlookMessageBatchOut:
    state = _require_active_run(connection, run_id)
    current_count = int(state.get("bodies_seen") or 0)
    if current_count + len(payload.items) > RUN_BUDGET:
        raise validation_error("The Outlook connector run exceeded its body budget.")
    if current_count + len(payload.items) > int(state.get("headers_seen") or 0):
        raise validation_error("The Outlook connector submitted more bodies than headers.")

    accepted = queued = committed = duplicate = ignored = 0
    for item in payload.items:
        fingerprint = store.message_fingerprint("outlook", item.source_id)
        authorized = connection.execute(
            """
            SELECT 1 FROM outlook_connector_body_tokens
            WHERE run_id = ? AND token_hash = ? AND fingerprint = ?
              AND header_hash = ? AND consumed = 0
            """,
            (run_id, _digest(item.body_token), fingerprint, _header_hash(item)),
        ).fetchone()
        if authorized is None:
            raise validation_error("The Outlook body token is invalid or already used.")
        connection.execute(
            """
            UPDATE outlook_connector_body_tokens SET consumed = 1
            WHERE run_id = ? AND token_hash = ?
            """,
            (run_id, _digest(item.body_token)),
        )
        if not is_likely_recruitment_header(item.subject, item.sender):
            ignored += 1
            continue
        if connection.execute(
            "SELECT 1 FROM mail_event_candidates WHERE fingerprint = ?", (fingerprint,)
        ).fetchone() is not None:
            duplicate += 1
            continue

        extra_reasons: list[str] = []
        body = item.body
        trimmed = None
        if item.body_status == "too_large":
            body = ""
            extra_reasons.append("body_too_large")
        elif item.body_status == "missing":
            body = ""
            extra_reasons.append("body_missing")
        else:
            try:
                if item.content_type == "html":
                    body = html_to_text(body)
                trimmed = trim_quoted_reply(body)
                body = trimmed.text
            except MailContentError:
                body = ""
                extra_reasons.append("body_too_large")
                trimmed = None

        extracted = classify_and_extract(
            subject=item.subject,
            sender=item.sender,
            received_at=item.received_at,
            body=body,
            quoted_only=bool(trimmed and trimmed.quoted_only),
            quoted_tail_trimmed=bool(trimmed and trimmed.trimmed),
        )
        if extracted.negative_signal:
            ignored += 1
            continue
        candidate, _, event = store.create_candidate(
            connection,
            provider="outlook",
            source_key=item.source_id,
            extracted=_extraction_mapping(extracted, extra_reasons),
        )
        if candidate is None:
            ignored += 1
            continue
        accepted += 1
        if event is not None:
            committed += 1
        elif candidate.state == "pending":
            queued += 1
        elif candidate.state == "duplicate":
            duplicate += 1
        del body, extracted

    connection.execute(
        "UPDATE outlook_connector_state SET bodies_seen = ?, updated_at = ? WHERE singleton_id = 1",
        (current_count + len(payload.items), now_iso()),
    )
    return OutlookMessageBatchOut(
        accepted_count=accepted,
        queued_count=queued,
        committed_count=committed,
        duplicate_count=duplicate,
        ignored_count=ignored,
    )


def complete_run(
    connection: sqlite3.Connection,
    run_id: str,
    payload: OutlookRunCompleteRequest,
) -> OutlookRunCompleteOut:
    state = _require_active_run(connection, run_id)
    leased = {
        row["id"]: dict(row)
        for row in connection.execute(
            "SELECT * FROM outlook_scan_windows WHERE leased_by_run_id = ?", (run_id,)
        ).fetchall()
    }
    supplied = {item.window_id: item for item in payload.windows}
    if set(leased) != set(supplied):
        raise validation_error("Completion must describe every leased Outlook scan window.")
    processed = sum(item.headers_processed for item in payload.windows)
    if processed != int(state.get("headers_seen") or 0):
        raise validation_error("Completion header count does not match the accepted batches.")
    unconsumed = int(
        connection.execute(
            """
            SELECT count(*) FROM outlook_connector_body_tokens
            WHERE run_id = ? AND consumed = 0
            """,
            (run_id,),
        ).fetchone()[0]
    )
    if unconsumed:
        raise validation_error("All gated Outlook message bodies must be resolved first.")

    for window_id, item in supplied.items():
        row = leased[window_id]
        seen = int(row["lease_headers_seen"] or 0)
        if item.headers_processed != seen:
            raise validation_error("Completion count does not match the scanned window.")
        if item.has_more:
            assert item.next_from_index is not None
            expected_next = int(row["lease_start_index"] or 0) + seen
            if item.next_from_index != expected_next or seen == 0:
                raise validation_error("Outlook pagination did not make progress.")
            connection.execute(
                """
                UPDATE outlook_scan_windows
                SET next_from_index = ?, leased_by_run_id = NULL,
                    lease_start_index = NULL, lease_headers_seen = 0,
                    lease_limit = NULL, updated_at = ?
                WHERE id = ?
                """,
                (item.next_from_index, now_iso(), window_id),
            )
        else:
            connection.execute("DELETE FROM outlook_scan_windows WHERE id = ?", (window_id,))

    connection.execute(
        "DELETE FROM outlook_connector_body_tokens WHERE run_id = ?", (run_id,)
    )

    pending_windows = int(
        connection.execute("SELECT count(*) FROM outlook_scan_windows").fetchone()[0]
    )
    headers_seen = int(state.get("headers_seen") or 0)
    bodies_seen = int(state.get("bodies_seen") or 0)
    timestamp = now_iso()
    connection.execute(
        """
        UPDATE outlook_connector_state
        SET status = 'connected', last_success_at = ?, last_error_code = NULL,
            active_run_id = NULL, lease_expires_at = NULL,
            headers_seen = 0, bodies_seen = 0, updated_at = ?
        WHERE singleton_id = 1
        """,
        (timestamp, timestamp),
    )
    return OutlookRunCompleteOut(
        pending_windows=pending_windows,
        processed_headers=headers_seen,
        processed_bodies=bodies_seen,
    )


def fail_run(
    connection: sqlite3.Connection,
    run_id: str,
    payload: OutlookRunFailRequest,
) -> OutlookRunFailOut:
    _require_active_run(connection, run_id)
    _release_run(connection, run_id)
    status = "needs_reauth" if payload.error_code == "connector_auth_required" else "error"
    connection.execute(
        """
        UPDATE outlook_connector_state
        SET status = ?, last_error_code = ?, active_run_id = NULL,
            lease_expires_at = NULL, headers_seen = 0, bodies_seen = 0,
            updated_at = ?
        WHERE singleton_id = 1
        """,
        (status, payload.error_code, now_iso()),
    )
    return OutlookRunFailOut(error_code=payload.error_code)


def pause(connection: sqlite3.Connection) -> MailAccountOut:
    state = ensure_state(connection)
    if state.get("active_run_id"):
        _release_run(connection, str(state["active_run_id"]))
    connection.execute(
        """
        UPDATE outlook_connector_state
        SET status = 'paused', active_run_id = NULL, lease_expires_at = NULL,
            headers_seen = 0, bodies_seen = 0, updated_at = ?
        WHERE singleton_id = 1
        """,
        (now_iso(),),
    )
    return account_out(connection)


def resume(connection: sqlite3.Connection) -> MailAccountOut:
    state = ensure_state(connection)
    if state["status"] != "paused":
        raise validation_error("Only a paused Outlook connector can be resumed.")
    status = "connected" if state.get("last_success_at") else "disconnected"
    connection.execute(
        """
        UPDATE outlook_connector_state
        SET status = ?, last_error_code = NULL, updated_at = ?
        WHERE singleton_id = 1
        """,
        (status, now_iso()),
    )
    return account_out(connection)


__all__ = [
    "account_out",
    "complete_run",
    "ensure_state",
    "fail_run",
    "gate_headers",
    "ingest_messages",
    "pause",
    "resume",
    "start_run",
]
