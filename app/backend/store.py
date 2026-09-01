"""Data access and business rules for the board."""

from __future__ import annotations

import sqlite3

from pydantic import ValidationError

from .clock import now_iso
from .config import Paths
from .database import open_connection
from .errors import (
    ApiError,
    match_conflict,
    not_found,
    stage_conflict,
    validation_error,
)
from .matching import MatchQuery, find_matching, normalize_text, normalize_url
from .schemas import (
    ApplicationBase,
    BoardCounts,
    CreateApplication,
    CreateEvent,
    EventOut,
    ListResponse,
    PatchApplication,
    PatchEvent,
    STAGES,
)

from contextlib import contextmanager


@contextmanager
def open_connection_tx(paths: Paths):
    connection = open_connection(paths)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


GROUP_STATUSES = {
    "pending_review": ["pending_review"],
    "applied": ["applied"],
    "assessment": ["assessment"],
    "interview": ["interview_1", "interview_2", "interview_3", "interview_hr"],
    "ended": ["offer", "rejected", "withdrawn"],
}

FINISHED_STATUSES = set(GROUP_STATUSES["ended"])
SORTABLE_FIELDS = {
    "company_name",
    "job_title",
    "current_status",
    "updated_at",
    "submitted_at",
    "created_at",
}


def _row_to_application(row: sqlite3.Row | dict) -> ApplicationBase:
    return ApplicationBase.model_validate(dict(row))


def _row_to_event(row: sqlite3.Row | dict) -> EventOut:
    return EventOut.model_validate(dict(row))


def get_application(connection: sqlite3.Connection, application_id: int) -> dict:
    row = connection.execute(
        "SELECT * FROM applications WHERE id = ?", (application_id,)
    ).fetchone()
    if row is None:
        raise not_found()
    return dict(row)


def get_event(connection: sqlite3.Connection, application_id: int, event_id: int) -> dict:
    row = connection.execute(
        """
        SELECT * FROM application_events
        WHERE id = ? AND application_id = ?
        """,
        (event_id, application_id),
    ).fetchone()
    if row is None:
        raise not_found()
    return dict(row)


def list_events(connection: sqlite3.Connection, application_id: int) -> list[EventOut]:
    rows = connection.execute(
        """
        SELECT * FROM application_events
        WHERE application_id = ?
        ORDER BY created_at DESC, id DESC
        """,
        (application_id,),
    ).fetchall()
    return [_row_to_event(row) for row in rows]


def create_application(
    connection: sqlite3.Connection, payload: CreateApplication
) -> ApplicationBase:
    timestamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO applications (
            company_name, job_title, department, job_code, application_type,
            location, source, job_url, current_status, filled_at, submitted_at,
            next_action, next_action_date, notes, created_at, updated_at, archived_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?, ?, NULL)
        """,
        (
            payload.company_name.strip(),
            payload.job_title.strip(),
            payload.department,
            payload.job_code,
            payload.application_type,
            payload.location,
            payload.source,
            normalize_url(payload.job_url),
            "pending_review",
            payload.next_action,
            payload.next_action_date,
            payload.notes,
            timestamp,
            timestamp,
        ),
    )
    application_id = cursor.lastrowid
    insert_event(
        connection,
        application_id,
        CreateEvent(stage="pending_review", event_date=payload.event_date, source="manual_ui"),
    )
    return _row_to_application(
        connection.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    )


def patch_application(
    connection: sqlite3.Connection, application_id: int, payload: PatchApplication
) -> ApplicationBase:
    record = get_application(connection, application_id)
    fields = payload.model_dump(exclude_unset=True)
    if "job_url" in fields:
        fields["job_url"] = normalize_url(fields["job_url"])
    if not fields:
        return _row_to_application(record)

    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values()) + [now_iso(), application_id]
    connection.execute(
        f"UPDATE applications SET {assignments}, updated_at = ? WHERE id = ?",
        values,
    )
    return _row_to_application(
        connection.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    )


def soft_delete(connection: sqlite3.Connection, application_id: int) -> None:
    record = get_application(connection, application_id)
    if record["archived_at"] is not None:
        return
    connection.execute(
        "UPDATE applications SET archived_at = ?, updated_at = ? WHERE id = ?",
        (now_iso(), now_iso(), application_id),
    )


def insert_event(connection: sqlite3.Connection, application_id: int, event: CreateEvent) -> EventOut:
    event.validate_stage_rules()
    timestamp = now_iso()
    cursor = connection.execute(
        """
        INSERT INTO application_events (
            application_id, stage, event_date, scheduled_date, scheduled_time,
            deadline_date, deadline_time, completed_date, timezone, mode, location,
            note, source, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            application_id,
            event.stage,
            event.event_date,
            event.scheduled_date,
            event.scheduled_time,
            event.deadline_date,
            event.deadline_time,
            event.completed_date,
            event.timezone or "Asia/Shanghai",
            event.mode,
            event.location,
            event.note,
            event.source,
            timestamp,
            timestamp,
        ),
    )
    if event.stage == "applied":
        connection.execute(
            "UPDATE applications SET submitted_at = ?, updated_at = ? WHERE id = ?",
            (event.event_date, timestamp, application_id),
        )
    connection.execute(
        "UPDATE applications SET current_status = ?, updated_at = ? WHERE id = ?",
        (event.stage, timestamp, application_id),
    )
    row = connection.execute(
        "SELECT * FROM application_events WHERE id = ?", (cursor.lastrowid,)
    ).fetchone()
    return _row_to_event(row)


def add_event(
    connection: sqlite3.Connection, application_id: int, payload: CreateEvent
) -> tuple[ApplicationBase, EventOut]:
    payload.validate_stage_rules()
    record = get_application(connection, application_id)
    if record["archived_at"] is not None:
        raise not_found()

    existing = connection.execute(
        """
        SELECT * FROM application_events
        WHERE application_id = ? AND stage = ? AND event_date = ?
          AND scheduled_date IS ? AND scheduled_time IS ?
          AND deadline_date IS ? AND deadline_time IS ?
        """,
        (
            application_id,
            payload.stage,
            payload.event_date,
            payload.scheduled_date,
            payload.scheduled_time,
            payload.deadline_date,
            payload.deadline_time,
        ),
    ).fetchone()

    if existing is not None:
        return _row_to_application(record), _row_to_event(existing)
    if record["current_status"] in FINISHED_STATUSES:
        raise stage_conflict(
            "This application already ended; confirm with the user before adding a new stage."
        )

    event = insert_event(connection, application_id, payload)
    updated = get_application(connection, application_id)
    return _row_to_application(updated), event


def patch_event(
    connection: sqlite3.Connection, application_id: int, event_id: int, payload: PatchEvent
) -> EventOut:
    record = get_application(connection, application_id)
    event = get_event(connection, application_id, event_id)
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return _row_to_event(event)

    merged_event = {
        key: event[key]
        for key in (
            "stage",
            "event_date",
            "scheduled_date",
            "scheduled_time",
            "deadline_date",
            "deadline_time",
            "completed_date",
            "timezone",
            "mode",
            "location",
            "note",
            "source",
        )
    }
    merged_event.update(fields)
    try:
        validated = CreateEvent.model_validate(merged_event)
    except ValidationError as exc:
        details = {
            "errors": [
                {
                    "field": ".".join(str(part) for part in error.get("loc", ())),
                    "message": error.get("msg", "Invalid value."),
                    "type": error.get("type", "validation_error"),
                }
                for error in exc.errors()
            ]
        }
        raise validation_error("Event update would create an invalid event.", details)
    validated.validate_stage_rules()
    fields = {name: getattr(validated, name) for name in fields}

    assignments = ", ".join(f"{name} = ?" for name in fields)
    values = list(fields.values()) + [now_iso(), event_id]
    connection.execute(
        f"UPDATE application_events SET {assignments}, updated_at = ? WHERE id = ?",
        values,
    )

    if "event_date" in fields and event["stage"] == "applied":
        connection.execute(
            "UPDATE applications SET submitted_at = ?, updated_at = ? WHERE id = ?",
            (fields["event_date"], now_iso(), application_id),
        )
    row = connection.execute(
        "SELECT * FROM application_events WHERE id = ?", (event_id,)
    ).fetchone()
    return _row_to_event(row)


def list_applications(
    connection: sqlite3.Connection,
    *,
    q: str | None = None,
    stage_group: str | None = None,
    status: str | None = None,
    application_type: str | None = None,
    city: str | None = None,
    source: str | None = None,
    sort: str = "updated_at",
    page: int = 1,
    page_size: int = 20,
) -> ListResponse:
    if stage_group and stage_group not in GROUP_STATUSES:
        raise validation_error("Unknown stage_group.")
    if status and status not in STAGES:
        raise validation_error("Unknown status.")

    def build(status_filter: bool) -> tuple[str, list]:
        clauses = ["archived_at IS NULL"]
        params: list = []
        if q:
            needle = f"%{q.strip()}%"
            clauses.append(
                "(company_name LIKE ? OR job_title LIKE ? OR department LIKE ? OR job_code LIKE ?)"
            )
            params.extend([needle, needle, needle, needle])
        if status_filter:
            if status:
                clauses.append("current_status = ?")
                params.append(status)
            elif stage_group:
                placeholders = ", ".join("?" for _ in GROUP_STATUSES[stage_group])
                clauses.append(f"current_status IN ({placeholders})")
                params.extend(GROUP_STATUSES[stage_group])
        if application_type:
            clauses.append("application_type = ?")
            params.append(application_type)
        if city:
            clauses.append("location = ?")
            params.append(city)
        if source:
            clauses.append("source = ?")
            params.append(source)
        return " AND ".join(clauses), params

    field = sort[1:] if sort.startswith("-") else sort
    explicit = sort.startswith("-")
    if field not in SORTABLE_FIELDS:
        raise validation_error(f"Unknown sort field: {field}")
    text_fields = {"company_name", "job_title"}
    if explicit:
        direction = "DESC" if field in text_fields else "ASC"
    else:
        direction = "ASC" if field in text_fields else "DESC"


    where, params = build(status_filter=True)
    aliased_where = (
        where.replace("archived_at", "a.archived_at")
        .replace("current_status", "a.current_status")
        .replace("application_type", "a.application_type")
        .replace("location", "a.location")
        .replace("source", "a.source")
        .replace("company_name", "a.company_name")
        .replace("job_title", "a.job_title")
        .replace("job_code", "a.job_code")
    )
    total = connection.execute(
        f"SELECT count(*) AS c FROM applications a WHERE {aliased_where}", params
    ).fetchone()["c"]

    offset = max(page - 1, 0) * page_size
    rows = connection.execute(
        f"""
        SELECT a.*,
               le.stage AS le_stage,
               le.event_date AS le_event_date,
               le.scheduled_date AS le_scheduled_date,
               le.scheduled_time AS le_scheduled_time,
               le.deadline_date AS le_deadline_date,
               le.deadline_time AS le_deadline_time,
               le.completed_date AS le_completed_date,
               le.mode AS le_mode,
               le.location AS le_location,
               le.note AS le_note,
               le.source AS le_source
        FROM applications a
        LEFT JOIN application_events le
            ON le.application_id = a.id
           AND le.id = (
               SELECT max(le2.id) FROM application_events le2
               WHERE le2.application_id = a.id
           )
        WHERE {where.replace("archived_at", "a.archived_at").replace("current_status", "a.current_status").replace("application_type", "a.application_type").replace("location", "a.location").replace("source", "a.source").replace("company_name", "a.company_name").replace("job_title", "a.job_title").replace("job_code", "a.job_code")}
        ORDER BY {field if field in ("updated_at", "created_at", "submitted_at", "company_name", "job_title", "current_status") else field} {direction}, a.id ASC
        LIMIT ? OFFSET ?
        """,
        [*params, page_size, offset],
    ).fetchall()

    event_keys = (
        "le_stage",
        "le_event_date",
        "le_scheduled_date",
        "le_scheduled_time",
        "le_deadline_date",
        "le_deadline_time",
        "le_completed_date",
        "le_mode",
        "le_location",
        "le_note",
        "le_source",
    )
    application_rows: list[dict] = []
    for row in rows:
        record = dict(row)
        if record.get("le_stage") is not None:
            record["latest_event"] = {
                "stage": record.pop("le_stage"),
                "event_date": record.pop("le_event_date"),
                "scheduled_date": record.pop("le_scheduled_date"),
                "scheduled_time": record.pop("le_scheduled_time"),
                "deadline_date": record.pop("le_deadline_date"),
                "deadline_time": record.pop("le_deadline_time"),
                "completed_date": record.pop("le_completed_date"),
                "mode": record.pop("le_mode"),
                "location": record.pop("le_location"),
                "note": record.pop("le_note"),
                "source": record.pop("le_source"),
            }
        else:
            record["latest_event"] = None
            for key in event_keys:
                record.pop(key, None)
        application_rows.append(record)

    count_where, count_params = build(status_filter=False)
    aliased_count_where = (
        count_where.replace("archived_at", "a.archived_at")
        .replace("current_status", "a.current_status")
        .replace("application_type", "a.application_type")
        .replace("location", "a.location")
        .replace("source", "a.source")
        .replace("company_name", "a.company_name")
        .replace("job_title", "a.job_title")
        .replace("job_code", "a.job_code")
    )
    group_rows = connection.execute(
        f"""
        SELECT a.current_status, count(*) AS c
        FROM applications a
        WHERE {aliased_count_where}
        GROUP BY a.current_status
        """,
        count_params,
    ).fetchall()
    counts_by_status = {row["current_status"]: row["c"] for row in group_rows}
    counts = BoardCounts(
        pending_review=sum(counts_by_status.get(s, 0) for s in GROUP_STATUSES["pending_review"]),
        applied=sum(counts_by_status.get(s, 0) for s in GROUP_STATUSES["applied"]),
        assessment=sum(counts_by_status.get(s, 0) for s in GROUP_STATUSES["assessment"]),
        interview=sum(counts_by_status.get(s, 0) for s in GROUP_STATUSES["interview"]),
        ended=sum(counts_by_status.get(s, 0) for s in GROUP_STATUSES["ended"]),
    )

    options_rows = connection.execute(
        """
        SELECT DISTINCT application_type FROM applications
        WHERE archived_at IS NULL AND application_type IS NOT NULL
        ORDER BY application_type
        """
    ).fetchall()
    city_rows = connection.execute(
        """
        SELECT DISTINCT location FROM applications
        WHERE archived_at IS NULL AND location IS NOT NULL
        ORDER BY location
        """
    ).fetchall()
    source_rows = connection.execute(
        """
        SELECT DISTINCT source FROM applications
        WHERE archived_at IS NULL AND source IS NOT NULL
        ORDER BY source
        """
    ).fetchall()

    return ListResponse(
        items=[_row_to_application(row) for row in application_rows],
        total=int(total),
        page=page,
        page_size=page_size,
        counts=counts,
        options={
            "types": [row["application_type"] for row in options_rows],
            "cities": [row["location"] for row in city_rows],
            "sources": [row["source"] for row in source_rows],
        },
    )


# ---------------------------------------------------------------------------
# Agent flows
# ---------------------------------------------------------------------------


def agent_fill_completed(
    connection: sqlite3.Connection, fields: dict[str, object]
) -> ApplicationBase:
    """Idempotently record a finished form fill as pending_review."""

    raw_company = fields.get("company_name")
    raw_title = fields.get("job_title")
    raw_url = fields.get("job_url")
    normalized = {
        "company_name": normalize_text(str(raw_company)) if raw_company else None,
        "job_title": normalize_text(str(raw_title)) if raw_title else None,
        "department": fields.get("department"),
        "job_code": fields.get("job_code"),
        "application_type": fields.get("application_type"),
        "location": fields.get("location"),
        "source": fields.get("source"),
        "job_url": normalize_url(str(raw_url)) if raw_url else None,
    }

    if not normalized["company_name"] or not normalized["job_title"]:
        raise validation_error("Company and job title are required for fill-completed.")

    query = MatchQuery(
        company_name=normalized["company_name"],
        job_title=normalized["job_title"],
        job_code=normalized["job_code"],
        location=normalized["location"],
        job_url=normalized["job_url"],
    )
    matches = find_matching(connection, query)
    if len(matches) > 1:
        raise match_conflict(len(matches))

    provided_filled_at = str(fields.get("filled_at") or "").strip()
    timestamp = now_iso()
    if not matches:
        cursor = connection.execute(
            """
            INSERT INTO applications (
                company_name, job_title, department, job_code, application_type,
                location, source, job_url, current_status, filled_at, submitted_at,
                next_action, next_action_date, notes, created_at, updated_at, archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending_review', ?, NULL, NULL, NULL, NULL, ?, ?, NULL)
            """,
            (
                fields["company_name"].strip(),
                fields["job_title"].strip(),
                normalized["department"],
                normalized["job_code"],
                normalized["application_type"],
                normalized["location"],
                normalized["source"],
                normalized["job_url"],
                provided_filled_at or timestamp,
                timestamp,
                timestamp,
            ),
        )
        insert_event(
            connection,
            cursor.lastrowid,
            CreateEvent(stage="pending_review", event_date=timestamp[:10], source="agent_fill"),
        )
        row = connection.execute(
            "SELECT * FROM applications WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        return _row_to_application(row)

    record = matches[0]
    if record["current_status"] != "pending_review":
        raise stage_conflict(
            "This application already left the pending review stage; the fill callback must not move it backwards."
        )

    updates = {
        "department": normalized["department"],
        "job_code": normalized["job_code"],
        "application_type": normalized["application_type"],
        "location": normalized["location"],
        "source": normalized["source"],
        "job_url": normalized["job_url"],
        "filled_at": provided_filled_at or timestamp,
        "updated_at": timestamp,
    }
    assignments = ", ".join(f"{name} = ?" for name in updates)
    connection.execute(
        f"UPDATE applications SET {assignments} WHERE id = ?",
        [*updates.values(), record["id"]],
    )
    row = connection.execute(
        "SELECT * FROM applications WHERE id = ?", (record["id"],)
    ).fetchone()
    return _row_to_application(row)


def agent_status_update(
    connection: sqlite3.Connection,
    match_fields: dict[str, object],
    event: CreateEvent,
) -> tuple[ApplicationBase, EventOut]:
    """Match a unique active record and append a validated stage event."""

    for key, value in match_fields.items():
        if key == "job_url" and value:
            match_fields[key] = str(value)
    query = MatchQuery.from_fields(match_fields)
    if not query.has_any():
        raise validation_error("The agent status update needs at least one match field.")

    matches = find_matching(connection, query)
    if not matches:
        raise not_found()
    if len(matches) > 1:
        raise match_conflict(len(matches))

    record = get_application(connection, matches[0]["id"])
    return add_event(connection, record["id"], event)
