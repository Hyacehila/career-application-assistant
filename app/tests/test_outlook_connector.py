"""Bounded, privacy-preserving Outlook connector ingestion protocol."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest

from backend import store as application_store
from backend.database import open_connection


def _start(client) -> dict:
    response = client.post("/api/mail/outlook-connector/runs", json={})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["state"] == "started"
    assert payload["run_id"]
    return payload


def _received_in(window: dict) -> str:
    start = datetime.fromisoformat(window["received_from"])
    end = datetime.fromisoformat(window["received_before"])
    return (end - min(timedelta(hours=1), (end - start) / 2)).isoformat()


def _header(window: dict, *, token: str = "h1", source_id: str = "source-1") -> dict:
    return {
        "token": token,
        "source_id": source_id,
        "subject": "第一轮面试邀请",
        "sender": "recruiting.example.invalid",
        "received_at": _received_in(window),
    }


def _gate(client, run: dict, window: dict, header: dict) -> dict:
    response = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/headers",
        json={
            "window_id": window["id"],
            "from_index": window["from_index"],
            "items": [header],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _message(header: dict, body_token: str, *, body: str, **overrides) -> dict:
    item = {
        **header,
        "body_token": body_token,
        "body": body,
        "content_type": "text",
        "body_status": "available",
    }
    item.update(overrides)
    return item


def _complete(client, run: dict, windows: list[dict]) -> dict:
    response = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/complete",
        json={"windows": windows},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_accounts_distinguish_connector_and_imap_and_outlook_local_actions_are_disabled(
    client,
) -> None:
    response = client.get("/api/mail/accounts")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [(item["provider"], item["connection_mode"]) for item in items] == [
        ("outlook", "codex_connector"),
        ("qq", "local_imap"),
        ("163", "local_imap"),
    ]

    connect = client.post(
        "/api/mail/accounts/outlook/connect",
        json={
            "mailbox_address": "person" + "@example.invalid",
            "authorization_code": "not-used",
        },
    )
    sync = client.post("/api/mail/accounts/outlook/sync", json={})
    disconnect = client.delete("/api/mail/accounts/outlook")
    assert (connect.status_code, sync.status_code, disconnect.status_code) == (422, 422, 422)


def test_run_lease_is_exclusive_recovers_after_expiry_and_pause_is_respected(client) -> None:
    first = _start(client)
    busy = client.post("/api/mail/outlook-connector/runs", json={})
    assert busy.status_code == 200
    assert busy.json() == {
        "state": "busy",
        "run_id": None,
        "lease_expires_at": None,
        "remaining_budget": 0,
        "windows": [],
    }

    with application_store.open_connection_tx(client.app.state.paths) as connection:
        connection.execute(
            "UPDATE outlook_connector_state SET lease_expires_at = ? WHERE singleton_id = 1",
            ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(),),
        )
    recovered = _start(client)
    assert recovered["run_id"] != first["run_id"]

    failed = client.post(
        f"/api/mail/outlook-connector/runs/{recovered['run_id']}/fail",
        json={"error_code": "connector_unavailable"},
    )
    assert failed.status_code == 200
    paused = client.post("/api/mail/accounts/outlook/pause", json={})
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert client.post("/api/mail/outlook-connector/runs", json={}).json()["state"] == "paused"
    resumed = client.post("/api/mail/accounts/outlook/resume", json={})
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "disconnected"


def test_simultaneous_run_requests_yield_one_lease_and_one_busy_result(client) -> None:
    barrier = Barrier(2)

    def start_together() -> tuple[int, dict]:
        barrier.wait()
        response = client.post("/api/mail/outlook-connector/runs", json={})
        return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: start_together(), range(2)))

    assert [status for status, _payload in results] == [200, 200]
    assert sorted(payload["state"] for _status, payload in results) == ["busy", "started"]
    started = next(payload for _status, payload in results if payload["state"] == "started")
    assert started["run_id"]


def test_window_progress_is_verified_and_backlog_resumes_without_cursor_jump(client) -> None:
    run = _start(client)
    window = run["windows"][0]
    assert window["kind"] == "backfill"
    header = _header(window, source_id="non-recruitment", token="page-1")
    header["subject"] = "Monthly account statement"
    header["sender"] = "system.example.invalid"
    gated = _gate(client, run, window, header)
    assert gated["body_tokens"] == []

    wrong = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/complete",
        json={
            "windows": [
                {
                    "window_id": window["id"],
                    "headers_processed": 1,
                    "has_more": True,
                    "next_from_index": window["from_index"] + 2,
                }
            ]
        },
    )
    assert wrong.status_code == 422

    completed = _complete(
        client,
        run,
        [
            {
                "window_id": window["id"],
                "headers_processed": 1,
                "has_more": True,
                "next_from_index": window["from_index"] + 1,
            }
        ],
    )
    assert completed["pending_windows"] == 1

    next_run = _start(client)
    assert sum(item["limit"] for item in next_run["windows"]) == 200
    backlog = next(item for item in next_run["windows"] if item["id"] == window["id"])
    assert backlog["from_index"] == 1
    assert {item["kind"] for item in next_run["windows"]} == {"live", "backfill"}


def test_body_tokens_are_server_issued_bound_single_use_and_required_before_completion(client) -> None:
    run = _start(client)
    window = run["windows"][0]
    header = _header(window)
    gated = _gate(client, run, window, header)
    body_token = gated["body_tokens"][0]["body_token"]
    assert gated["body_tokens"][0]["token"] == header["token"]
    assert header["source_id"] not in json.dumps(gated)

    premature = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/complete",
        json={
            "windows": [
                {
                    "window_id": window["id"],
                    "headers_processed": 1,
                    "has_more": False,
                }
            ]
        },
    )
    assert premature.status_code == 422

    invalid = _message(header, "x" * 43, body="第一轮面试时间：2026年9月8日 10:00")
    rejected = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/messages",
        json={"items": [invalid]},
    )
    assert rejected.status_code == 422

    changed = _message(
        {**header, "subject": "第二轮面试邀请"},
        body_token,
        body="第二轮面试时间：2026年9月8日 10:00",
    )
    rejected = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/messages",
        json={"items": [changed]},
    )
    assert rejected.status_code == 422

    accepted = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/messages",
        json={
            "items": [
                _message(
                    header,
                    body_token,
                    body="第一轮面试时间：2026年9月8日 10:00",
                )
            ]
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["queued_count"] == 1

    replay = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/messages",
        json={"items": [_message(header, body_token, body="第一轮面试时间：2026年9月8日")]},
    )
    assert replay.status_code == 422


def test_structured_auto_commit_and_raw_mail_never_reach_database_response_or_logs(
    client, caplog
) -> None:
    application = client.post(
        "/api/applications",
        json={
            "company_name": "示例云科技",
            "job_title": "数据工程师",
            "job_code": "SYN-CONNECTOR-1",
            "location": "上海",
            "event_date": "2026-09-01",
        },
    ).json()
    run = _start(client)
    window = run["windows"][0]
    subject_marker = "RAW-SUBJECT-6f91"
    sender_marker = "raw-sender-6f91.example.invalid"
    source_marker = "RAW-MESSAGE-ID-6f91"
    body_marker = "RAW-BODY-6f91"
    private_markers = [
        subject_marker,
        sender_marker,
        source_marker,
        body_marker,
        "OTP-619144",
        "meeting-secret-6f91",
        "attachment-private-6f91.pdf",
    ]
    header = _header(window, source_id=source_marker)
    header["subject"] = f"第一轮面试邀请 {subject_marker}"
    header["sender"] = sender_marker
    gated = _gate(client, run, window, header)
    token = gated["body_tokens"][0]["body_token"]
    body = (
        "公司：示例云科技\n岗位：数据工程师\n职位编号：SYN-CONNECTOR-1\n"
        "工作地点：上海\n第一轮面试时间：2026年9月8日 10:00\n"
        f"{body_marker} OTP-619144 https://meet.invalid/meeting-secret-6f91 "
        "attachment-private-6f91.pdf"
    )
    response = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/messages",
        json={"items": [_message(header, token, body=body)]},
    )
    assert response.status_code == 200
    assert response.json()["committed_count"] == 1
    response_text = response.text

    connection = open_connection(client.app.state.paths)
    try:
        database_text = "\n".join(connection.iterdump())
        record = application_store.get_application(connection, application["id"])
        events = application_store.list_events(connection, application["id"])
    finally:
        connection.close()
    assert record["current_status"] == "interview_1"
    assert any(event.source == "email_extract" for event in events)
    log_text = caplog.text
    for marker in private_markers:
        assert marker not in database_text
        assert marker not in response_text
        assert marker not in log_text


def test_body_size_html_time_and_failure_code_boundaries_are_sanitized(client) -> None:
    run = _start(client)
    window = run["windows"][0]
    header = _header(window, source_id="oversized-body")
    gated = _gate(client, run, window, header)
    token = gated["body_tokens"][0]["body_token"]

    huge_marker = "PRIVATE-HUGE-MARKER"
    oversized = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/messages",
        json={
            "items": [
                _message(header, token, body=huge_marker + ("界" * 180_000))
            ]
        },
    )
    assert oversized.status_code == 422
    assert huge_marker not in oversized.text

    accepted = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/messages",
        json={
            "items": [
                _message(
                    header,
                    token,
                    body="",
                    body_status="too_large",
                )
            ]
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["queued_count"] == 1

    naive = _header(window, token="naive", source_id="naive-time")
    naive["received_at"] = "2026-09-04T10:00:00"
    response = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/headers",
        json={
            "window_id": window["id"],
            "from_index": window["from_index"] + 1,
            "items": [naive],
        },
    )
    assert response.status_code == 422

    invalid_failure = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/fail",
        json={"error_code": "raw-provider-exception"},
    )
    assert invalid_failure.status_code == 422


@pytest.mark.parametrize(
    ("subject", "body", "expected_stage"),
    [
        ("Your application has been received", "Company: Example Labs", "applied"),
        ("Employment offer letter", "Company: Example Labs", "offer"),
        ("We regret to inform you", "Company: Example Labs", "rejected"),
        ("面试邀请", "面试时间：2026年9月8日 10:00", "interview_unspecified"),
        ("第一轮面试邀请", "面试时间：09/10 10:00", "interview_1"),
    ],
)
def test_unsafe_or_ambiguous_stages_always_enter_review(
    client, subject: str, body: str, expected_stage: str
) -> None:
    run = _start(client)
    window = run["windows"][0]
    header = _header(window, source_id=f"review-{expected_stage}")
    header["subject"] = subject
    gated = _gate(client, run, window, header)
    assert gated["body_tokens"]
    token = gated["body_tokens"][0]["body_token"]
    ingested = client.post(
        f"/api/mail/outlook-connector/runs/{run['run_id']}/messages",
        json={"items": [_message(header, token, body=body)]},
    )
    assert ingested.status_code == 200
    assert ingested.json()["committed_count"] == 0
    assert ingested.json()["queued_count"] == 1
    candidates = client.get("/api/mail/candidates", params={"state": "pending"}).json()
    assert candidates["items"][0]["proposed_stage"] == expected_stage
