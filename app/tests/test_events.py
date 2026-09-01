"""Stage 2: status events, date rules, transactional consistency, patches."""

from __future__ import annotations

from backend.database import open_connection


def _create(client, company="示例科技", job="前端工程师") -> dict:
    resp = client.post(
        "/api/applications",
        json={"company_name": company, "job_title": job, "event_date": "2026-08-01"},
    )
    assert resp.status_code == 201
    return resp.json()


def test_event_updates_status_in_same_transaction(client):
    created = _create(client)
    resp = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "applied", "event_date": "2026-08-05", "source": "user_confirmation"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["application"]["current_status"] == "applied"
    assert body["application"]["submitted_at"] == "2026-08-05"
    assert body["event"]["stage"] == "applied"


def test_interview_without_scheduled_date_is_422(client):
    created = _create(client)
    for stage in ("interview_1", "interview_2", "interview_3", "interview_hr"):
        resp = client.post(
            f"/api/applications/{created['id']}/events",
            json={"stage": stage, "event_date": "2026-08-10"},
        )
        assert resp.status_code == 422, stage


def test_interview_with_date_succeeds(client):
    created = _create(client)
    resp = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "interview_1",
            "event_date": "2026-08-10",
            "scheduled_date": "2026-08-15",
            "scheduled_time": "10:30",
            "mode": "online",
            "location": "视频会议",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["event"]["scheduled_time"] == "10:30"


def test_assessment_requires_a_date(client):
    created = _create(client)
    resp = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "assessment", "event_date": "2026-08-10"},
    )
    assert resp.status_code == 422
    resp = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "assessment", "event_date": "2026-08-10", "deadline_date": "2026-08-20"},
    )
    assert resp.status_code == 201


def test_time_zero_sentinel_rejected(client):
    created = _create(client)
    resp = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "interview_1",
            "event_date": "2026-08-10",
            "scheduled_date": "2026-08-15",
            "scheduled_time": "00:00",
        },
    )
    assert resp.status_code == 422
    # Missing time stays null, not 00:00.
    resp = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "interview_1", "event_date": "2026-08-10", "scheduled_date": "2026-08-15"},
    )
    assert resp.status_code == 201
    assert resp.json()["event"]["scheduled_time"] is None


def test_patch_event_keeps_id_and_updates_timestamp(client):
    created = _create(client)
    event = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "interview_2", "event_date": "2026-08-12", "scheduled_date": "2026-08-25"},
    ).json()["event"]
    resp = client.patch(
        f"/api/applications/{created['id']}/events/{event['id']}",
        json={"scheduled_date": "2026-08-26", "note": "改期"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == event["id"]
    assert body["scheduled_date"] == "2026-08-26"
    assert body["updated_at"] != event["updated_at"]


def test_completion_date_can_be_created_serialized_changed_and_cleared(client):
    created = _create(client)
    response = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "assessment",
            "event_date": "2026-08-10",
            "scheduled_date": "2026-08-20",
            "completed_date": "2026-08-21",
        },
    )
    assert response.status_code == 201
    event = response.json()["event"]
    assert event["completed_date"] == "2026-08-21"

    listing = client.get("/api/applications", params={"page_size": 100}).json()
    listed = next(item for item in listing["items"] if item["id"] == created["id"])
    assert listed["latest_event"]["completed_date"] == "2026-08-21"

    changed = client.patch(
        f"/api/applications/{created['id']}/events/{event['id']}",
        json={"completed_date": "2026-08-22"},
    )
    assert changed.status_code == 200
    assert changed.json()["completed_date"] == "2026-08-22"

    cleared = client.patch(
        f"/api/applications/{created['id']}/events/{event['id']}",
        json={"completed_date": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["completed_date"] is None
    detail = client.get(f"/api/applications/{created['id']}").json()
    assert detail["events"][0]["completed_date"] is None


def test_completion_date_is_limited_to_assessment_and_exact_interviews(client):
    created = _create(client)
    invalid = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "applied",
            "event_date": "2026-08-10",
            "source": "user_confirmation",
            "completed_date": "2026-08-10",
        },
    )
    assert invalid.status_code == 422

    interview = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "interview_hr",
            "event_date": "2026-08-12",
            "scheduled_date": "2026-08-20",
        },
    ).json()["event"]
    completed = client.patch(
        f"/api/applications/{created['id']}/events/{interview['id']}",
        json={"completed_date": "2026-08-20"},
    )
    assert completed.status_code == 200
    assert completed.json()["completed_date"] == "2026-08-20"


def test_completion_date_rejects_invalid_or_future_dates(client):
    created = _create(client)
    event = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "assessment",
            "event_date": "2026-08-10",
            "deadline_date": "2026-08-20",
        },
    ).json()["event"]
    for invalid in ("2026-02-30", "2999-01-01"):
        response = client.patch(
            f"/api/applications/{created['id']}/events/{event['id']}",
            json={"completed_date": invalid},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"


def test_patch_applied_event_resyncs_submitted_at(client):
    created = _create(client)
    client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "applied", "event_date": "2026-08-05", "source": "user_confirmation"},
    )
    connection = open_connection(client.app.state.paths)
    rows = connection.execute(
        "SELECT * FROM application_events WHERE stage = 'applied'"
    ).fetchall()
    connection.close()
    event_id = rows[0]["id"]
    client.patch(
        f"/api/applications/{created['id']}/events/{event_id}",
        json={"event_date": "2026-08-06"},
    )
    after = client.get(f"/api/applications/{created['id']}").json()["application"]
    assert after["submitted_at"] == "2026-08-06"


def test_finished_record_conflicts_with_new_stage(client):
    created = _create(client)
    client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "offer", "event_date": "2026-08-20"},
    )
    resp = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "interview_1", "event_date": "2026-08-21", "scheduled_date": "2026-08-28"},
    )
    assert resp.status_code == 409


def test_duplicate_event_is_idempotent(client):
    created = _create(client)
    first = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "applied", "event_date": "2026-08-05", "source": "user_confirmation"},
    ).json()["event"]
    second = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "applied", "event_date": "2026-08-05", "source": "user_confirmation"},
    ).json()["event"]
    assert second["id"] == first["id"]
    body = client.get(f"/api/applications/{created['id']}").json()
    assert len([e for e in body["events"] if e["stage"] == "applied"]) == 1


def test_invalid_stage_rejected(client):
    created = _create(client)
    resp = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "interview_4", "event_date": "2026-08-10"},
    )
    assert resp.status_code == 422


def test_invalid_calendar_dates_are_rejected(client):
    for invalid_date in ("2026-02-30", "2025-02-29"):
        response = client.post(
            "/api/applications",
            json={
                "company_name": "示例科技",
                "job_title": "前端工程师",
                "event_date": invalid_date,
            },
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"


def test_orphan_event_times_are_rejected(client):
    created = _create(client)
    scheduled = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "assessment",
            "event_date": "2026-08-10",
            "deadline_date": "2026-08-20",
            "scheduled_time": "09:30",
        },
    )
    assert scheduled.status_code == 422

    deadline = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "assessment",
            "event_date": "2026-08-10",
            "scheduled_date": "2026-08-15",
            "deadline_time": "18:00",
        },
    )
    assert deadline.status_code == 422


def test_patch_event_revalidates_merged_interview_and_assessment(client):
    created = _create(client)
    interview = client.post(
        f"/api/applications/{created['id']}/events",
        json={
            "stage": "interview_1",
            "event_date": "2026-08-10",
            "scheduled_date": "2026-08-15",
        },
    ).json()["event"]
    response = client.patch(
        f"/api/applications/{created['id']}/events/{interview['id']}",
        json={"scheduled_date": None},
    )
    assert response.status_code == 422

    invalid_event_date = client.patch(
        f"/api/applications/{created['id']}/events/{interview['id']}",
        json={"event_date": None},
    )
    assert invalid_event_date.status_code == 422
    assert invalid_event_date.json()["code"] == "validation_error"

    second = _create(client, company="另一公司")
    assessment = client.post(
        f"/api/applications/{second['id']}/events",
        json={
            "stage": "assessment",
            "event_date": "2026-08-10",
            "deadline_date": "2026-08-20",
        },
    ).json()["event"]
    response = client.patch(
        f"/api/applications/{second['id']}/events/{assessment['id']}",
        json={"deadline_date": None},
    )
    assert response.status_code == 422


def test_duplicate_finished_event_is_idempotent(client):
    created = _create(client)
    first = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "offer", "event_date": "2026-08-20"},
    ).json()["event"]
    second_response = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "offer", "event_date": "2026-08-20"},
    )
    assert second_response.status_code == 201
    assert second_response.json()["event"]["id"] == first["id"]


def test_manual_applied_event_requires_explicit_confirmation(client):
    created = _create(client)
    response = client.post(
        f"/api/applications/{created['id']}/events",
        json={"stage": "applied", "event_date": "2026-08-05", "source": "manual_ui"},
    )
    assert response.status_code == 422


def test_unknown_application_404(client):
    resp = client.post(
        "/api/applications/999/events",
        json={"stage": "applied", "event_date": "2026-08-05", "source": "user_confirmation"},
    )
    assert resp.status_code == 404
