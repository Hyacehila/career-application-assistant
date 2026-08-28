"""Stage 2/3: agent fill-completed and status-update closed loops."""

from __future__ import annotations

from backend.database import open_connection

FILL_BODY = {
    "company_name": "示例科技",
    "job_title": "前端工程师",
    "department": "平台部",
    "job_code": "FE-101",
    "application_type": "实习",
    "location": "上海",
    "source": "官网",
    "job_url": "https://jobs.example.com/careers/fe-101?utm_source=mail&ref=abc/",
    "filled_at": "2026-08-27T15:00:00+08:00",
}


def test_fill_completed_creates_pending_review(client):
    resp = client.post("/api/agent/fill-completed", json=FILL_BODY)
    assert resp.status_code == 201
    body = resp.json()
    assert body["current_status"] == "pending_review"
    assert body["filled_at"] == FILL_BODY["filled_at"]
    # URL is normalized: query, fragment, auth and trailing slash removed.
    assert body["job_url"] == "https://jobs.example.com/careers/fe-101"

    detail = client.get(f"/api/applications/{body['id']}").json()
    assert detail["application"]["current_status"] == "pending_review"
    assert len(detail["events"]) == 1
    assert detail["events"][0]["source"] == "agent_fill"


def test_fill_completed_is_idempotent(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    first = client.get("/api/applications").json()["items"][0]
    resp = client.post("/api/agent/fill-completed", json=FILL_BODY)
    assert resp.status_code == 201
    assert resp.json()["id"] == first["id"]
    listing = client.get("/api/applications").json()
    assert listing["total"] == 1
    detail = client.get(f"/api/applications/{first['id']}").json()
    pending_events = [e for e in detail["events"] if e["stage"] == "pending_review"]
    assert len(pending_events) == 1


def test_fill_completed_conflicts_when_already_applied(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    app_id = client.get("/api/applications").json()["items"][0]["id"]
    client.post(
        f"/api/applications/{app_id}/events",
        json={"stage": "applied", "event_date": "2026-08-27", "source": "user_confirmation"},
    )
    resp = client.post("/api/agent/fill-completed", json=FILL_BODY)
    assert resp.status_code == 409
    after = client.get(f"/api/applications/{app_id}").json()["application"]
    assert after["current_status"] == "applied"


def test_fill_completed_requires_company_and_job(client):
    body = dict(FILL_BODY)
    body["company_name"] = ""
    resp = client.post("/api/agent/fill-completed", json=body)
    assert resp.status_code == 422


def test_fill_completed_multi_match_conflict(client):
    client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "前端工程师",
            "location": "上海",
            "event_date": "2026-08-01",
        },
    )
    client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "前端工程师",
            "location": "上海",
            "event_date": "2026-08-01",
        },
    )
    # Same company, title and location -> strict third-level match stays ambiguous.
    body = {
        "company_name": "示例科技",
        "job_title": "前端工程师",
        "location": "上海",
        "filled_at": "2026-08-27T16:00:00+08:00",
    }
    resp = client.post("/api/agent/fill-completed", json=body)
    assert resp.status_code == 409
    assert resp.json()["details"]["candidate_count"] == 2


def test_status_update_applied_from_user_confirmation(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"company_name": "示例科技", "job_title": "前端工程师", "job_url": "https://jobs.example.com/careers/fe-101"},
            "event": {"stage": "applied", "event_date": "2026-08-27", "source": "user_confirmation"},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["application"]["current_status"] == "applied"
    assert resp.json()["application"]["submitted_at"] == "2026-08-27"


def test_status_update_interview_email(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"company_name": "示例科技", "job_title": "前端工程师", "location": "上海"},
            "event": {
                "stage": "interview_1",
                "event_date": "2026-08-28",
                "scheduled_date": "2026-08-30",
                "scheduled_time": "14:00",
                "mode": "online",
                "source": "email_extract",
            },
        },
    )
    assert resp.status_code == 200
    event = resp.json()["event"]
    assert event["stage"] == "interview_1"
    assert event["source"] == "email_extract"


def test_status_update_missing_date_is_422(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"company_name": "示例科技", "job_title": "前端工程师", "location": "上海"},
            "event": {"stage": "interview_2", "event_date": "2026-08-28", "source": "email_extract"},
        },
    )
    assert resp.status_code == 422


def test_status_update_no_match_404(client):
    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"company_name": "不存在公司"},
            "event": {"stage": "applied", "event_date": "2026-08-28", "source": "user_confirmation"},
        },
    )
    assert resp.status_code == 404


def test_status_update_multi_match_409(client):
    client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "测试工程师",
            "location": "上海",
            "event_date": "2026-08-01",
        },
    )
    client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "测试工程师",
            "location": "上海",
            "event_date": "2026-08-01",
        },
    )
    # Same company + title + location -> ambiguous at the strict third level.
    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"company_name": "示例科技", "job_title": "测试工程师", "location": "上海"},
            "event": {"stage": "applied", "event_date": "2026-08-28", "source": "user_confirmation"},
        },
    )
    assert resp.status_code == 409




def test_status_update_finished_conflict_409(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    app_id = client.get("/api/applications").json()["items"][0]["id"]
    client.post(
        f"/api/applications/{app_id}/events",
        json={"stage": "rejected", "event_date": "2026-08-20"},
    )
    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"job_url": "https://jobs.example.com/careers/fe-101"},
            "event": {"stage": "offer", "event_date": "2026-08-21"},
        },
    )
    assert resp.status_code == 409


def test_agent_payload_rejects_extra_fields(client):
    body = dict(FILL_BODY)
    body["candidate_email"] = "候选人的邮箱值"
    resp = client.post("/api/agent/fill-completed", json=body)
    assert resp.status_code == 422

    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"company_name": "示例科技"},
            "event": {
                "stage": "applied",
                "event_date": "2026-08-28",
                "email_body": "原始邮件正文",
            },
        },
    )
    assert resp.status_code == 422


def test_status_update_sensitive_match_fields_rejected(client):
    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"candidate_name": "张三"},
            "event": {"stage": "applied", "event_date": "2026-08-28"},
        },
    )
    assert resp.status_code == 422


def test_matching_normalization(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    # Half-width case/space differences still match; URL normalized both sides.
    resp = client.post(
        "/api/agent/status-update",
        json={
            "match": {"company_name": "  示例科技  ", "job_url": "https://JOBS.example.com/careers/FE-101/?x=1"},
            "event": {"stage": "applied", "event_date": "2026-08-27", "source": "user_confirmation"},
        },
    )
    assert resp.status_code == 200


def test_third_level_match_requires_location(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    response = client.post(
        "/api/agent/status-update",
        json={
            "match": {"company_name": "示例科技", "job_title": "前端工程师"},
            "event": {
                "stage": "interview_1",
                "event_date": "2026-08-28",
                "scheduled_date": "2026-08-30",
                "source": "email_extract",
            },
        },
    )
    assert response.status_code == 404


def test_agent_applied_requires_user_confirmation_source(client):
    client.post("/api/agent/fill-completed", json=FILL_BODY)
    response = client.post(
        "/api/agent/status-update",
        json={
            "match": {"job_url": "https://jobs.example.com/careers/fe-101"},
            "event": {
                "stage": "applied",
                "event_date": "2026-08-28",
                "source": "email_extract",
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_agent_fill_rejects_unknown_application_type(client):
    body = dict(FILL_BODY)
    body["application_type"] = "未知类型"
    response = client.post("/api/agent/fill-completed", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
