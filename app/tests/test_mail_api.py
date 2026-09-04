"""Public mailbox API contract and manual-review behavior."""

from __future__ import annotations

from backend import store as application_store
from backend.mail import store as mail_store


def test_accounts_endpoint_always_returns_three_provider_cards(client) -> None:
    response = client.get("/api/mail/accounts")
    assert response.status_code == 200
    body = response.json()
    assert [item["provider"] for item in body["items"]] == ["outlook", "qq", "163"]
    assert all(item["status"] == "disconnected" for item in body["items"])
    assert body["pending_count"] == 0


def test_parameterless_mail_posts_require_json_and_preserve_validation(client) -> None:
    without_json = client.post("/api/mail/accounts/qq/sync")
    assert without_json.status_code == 415
    assert without_json.json()["code"] == "not_json"

    with_json = client.post("/api/mail/accounts/qq/sync", json={})
    assert with_json.status_code == 422
    assert with_json.json()["code"] == "validation_error"


def test_candidate_review_api_exposes_only_structured_fields_and_commits(client) -> None:
    created = client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "后端工程师",
            "event_date": "2026-08-01",
        },
    ).json()
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        candidate, _, _ = mail_store.create_candidate(
            connection,
            provider="qq",
            source_key="71:901",
            extracted={
                "proposed_stage": "interview_unspecified",
                "event_date": "2026-08-30",
                "company_name": "示例科技",
                "job_title": "后端工程师",
                "review_reasons": ["generic_interview"],
            },
        )

    listing = client.get("/api/mail/candidates", params={"state": "pending"})
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert set(item) == {
        "id",
        "provider",
        "state",
        "company_name",
        "job_title",
        "proposed_stage",
        "event_date",
        "scheduled_date",
        "scheduled_time",
        "deadline_date",
        "deadline_time",
        "timezone",
        "confidence",
        "matched_application_id",
        "review_reasons",
        "expires_at",
    }
    assert "generic_interview" in item["review_reasons"]

    committed = client.post(
        f"/api/mail/candidates/{candidate.id}/confirm",
        json={
            "application_id": created["id"],
            "stage": "interview_1",
            "scheduled_date": "2026-09-04",
            "timezone": "Asia/Shanghai",
            "confirm_personally_submitted": False,
        },
    )
    assert committed.status_code == 200
    payload = committed.json()
    assert payload["candidate"]["state"] == "committed"
    assert payload["candidate"]["company_name"] is None
    assert payload["event"]["source"] == "email_extract"
    assert payload["application"]["current_status"] == "interview_1"


def test_applied_candidate_requires_explicit_personal_confirmation(client) -> None:
    created = client.post(
        "/api/applications",
        json={
            "company_name": "示例科技",
            "job_title": "后端工程师",
            "event_date": "2026-08-01",
        },
    ).json()
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        candidate, _, _ = mail_store.create_candidate(
            connection,
            provider="163",
            source_key="81:902",
            extracted={
                "proposed_stage": "applied",
                "event_date": "2026-08-30",
                "company_name": "示例科技",
                "job_title": "后端工程师",
            },
        )

    body = {
        "application_id": created["id"],
        "stage": "applied",
        "timezone": "Asia/Shanghai",
        "confirm_personally_submitted": False,
    }
    rejected = client.post(f"/api/mail/candidates/{candidate.id}/confirm", json=body)
    assert rejected.status_code == 422

    body["confirm_personally_submitted"] = True
    confirmed = client.post(f"/api/mail/candidates/{candidate.id}/confirm", json=body)
    assert confirmed.status_code == 200
    assert confirmed.json()["event"]["source"] == "user_confirmation"


def test_dismiss_redacts_pending_candidate(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        candidate, _, _ = mail_store.create_candidate(
            connection,
            provider="qq",
            source_key="91:903",
            extracted={
                "proposed_stage": "offer",
                "event_date": "2026-08-30",
                "company_name": "待删除的结构化公司名",
            },
        )

    response = client.post(f"/api/mail/candidates/{candidate.id}/dismiss", json={})
    assert response.status_code == 204
    dismissed = client.get("/api/mail/candidates", params={"state": "dismissed"}).json()["items"][0]
    assert dismissed["state"] == "dismissed"
    assert dismissed["company_name"] is None
    assert dismissed["proposed_stage"] is None
