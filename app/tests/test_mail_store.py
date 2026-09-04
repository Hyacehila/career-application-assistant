"""Structured mail persistence, review, and automatic-transition policy."""

from __future__ import annotations

from datetime import date

from backend import store as application_store
from backend.database import open_connection
from backend.mail import store
from backend.mail.schemas import MailCandidateConfirmRequest
from backend.schemas import CreateApplication, CreateEvent


def _application(connection, *, status: str = "applied"):
    record = application_store.create_application(
        connection,
        CreateApplication(
            company_name="示例云科技",
            job_title="数据工程师",
            job_code="SYN-101",
            location="上海",
            job_url="https://jobs.example.test/syn-101",
            event_date="2026-08-01",
        ),
    )
    if status != "pending_review":
        source = "user_confirmation" if status == "applied" else "manual_ui"
        event = CreateEvent(stage=status, event_date="2026-08-02", source=source)
        if status == "assessment":
            event.scheduled_date = "2026-08-03"
        application_store.add_event(connection, record.id, event)
    return application_store.get_application(connection, record.id)


def _account(connection, provider: str = "qq") -> dict:
    return store.ensure_account(connection, provider)


def test_schema_v2_contains_mail_tables(client) -> None:
    connection = open_connection(client.app.state.paths)
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        connection.close()
    assert {"mail_accounts", "mail_sync_cursors", "mail_event_candidates"} <= tables


def test_high_confidence_assessment_auto_commits(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        record = _application(connection)
        candidate, updated, event = store.create_candidate(
            connection,
            provider="outlook",
            source_key="immutable-synthetic-1",
            extracted={
                "proposed_stage": "assessment",
                "company_name": "示例云科技",
                "job_title": "数据工程师",
                "job_code": "SYN-101",
                "event_date": "2026-08-20",
                "deadline_date": "2026-08-25",
                "timezone": "Asia/Shanghai",
            },
        )
    assert candidate is not None
    assert candidate.state == "committed"
    assert candidate.confidence == 100
    assert updated["id"] == record["id"]
    assert event["stage"] == "assessment"
    assert event["source"] == "email_extract"


def test_generic_interview_and_missing_match_stay_pending(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        candidate, updated, event = store.create_candidate(
            connection,
            provider="qq",
            source_key="55:701",
            extracted={
                "proposed_stage": "interview_unspecified",
                "event_date": "2026-08-20",
                "scheduled_date": "2026-08-25",
                "review_reasons": ["generic_interview"],
            },
        )
    assert candidate is not None
    assert candidate.state == "pending"
    assert candidate.matched_application_id is None
    assert "missing_match" in candidate.review_reasons
    assert updated is None
    assert event is None


def test_terminal_event_never_auto_commits(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        _application(connection)
        candidate, _, event = store.create_candidate(
            connection,
            provider="163",
            source_key="77:900",
            extracted={
                "proposed_stage": "offer",
                "company_name": "示例云科技",
                "job_title": "数据工程师",
                "job_code": "SYN-101",
                "event_date": "2026-08-20",
            },
        )
    assert candidate is not None
    assert candidate.state == "pending"
    assert "manual_stage" in candidate.review_reasons
    assert event is None


def test_candidate_store_rejects_contact_details_in_public_labels(client) -> None:
    contact_address = "private-contact" + "@" + "contact.example"
    contact_number = "138" + "0000" + "0000"
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        candidate, _, _ = store.create_candidate(
            connection,
            provider="qq",
            source_key="contact-redaction-fixture",
            extracted={
                "proposed_stage": "interview_unspecified",
                "event_date": "2026-08-20",
                "company_name": f"示例科技 {contact_address}",
                "job_title": f"后端工程师 {contact_number}",
            },
        )
        row = connection.execute(
            "SELECT company_name, job_title FROM mail_event_candidates WHERE id = ?",
            (candidate.id,),
        ).fetchone()

    assert candidate.company_name is None
    assert candidate.job_title is None
    assert row["company_name"] is None
    assert row["job_title"] is None


def test_manual_confirmation_uses_candidate_received_date(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        record = _application(connection)
        candidate, _, _ = store.create_candidate(
            connection,
            provider="qq",
            source_key="12:901",
            extracted={
                "proposed_stage": "interview_unspecified",
                "event_date": "2026-08-21",
            },
        )
        committed, updated, event = store.confirm_candidate(
            connection,
            candidate.id,
            MailCandidateConfirmRequest(
                application_id=record["id"],
                stage="interview_1",
                scheduled_date="2026-08-28",
            ),
        )
    assert committed.state == "committed"
    assert committed.company_name is None
    assert updated["current_status"] == "interview_1"
    assert event["event_date"] == "2026-08-21"
    assert event["scheduled_date"] == "2026-08-28"


def test_expiry_and_disconnect_redact_but_keep_fingerprint(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        account = _account(connection, "163")
        candidate, _, _ = store.create_candidate(
            connection,
            provider="163",
            source_key="88:902",
            extracted={
                "proposed_stage": "rejected",
                "company_name": "仅用于测试的公司",
                "event_date": "2026-08-21",
            },
        )
        connection.execute(
            "UPDATE mail_event_candidates SET expires_at = '2000-01-01T00:00:00+08:00' WHERE id = ?",
            (candidate.id,),
        )
        store.disconnect_account(connection, "163")
        assert store.expire_pending_candidates(connection) == 1
        row = connection.execute(
            "SELECT * FROM mail_event_candidates WHERE id = ?", (candidate.id,)
        ).fetchone()
        account_row = store.get_account(connection, "163")
    assert row["state"] == "expired"
    assert row["fingerprint"]
    assert row["company_name"] is None
    assert account_row["status"] == "disconnected"


def test_quote_only_signal_never_auto_commits(client) -> None:
    with application_store.open_connection_tx(client.app.state.paths) as connection:
        _application(connection)
        candidate, _, event = store.create_candidate(
            connection,
            provider="qq",
            source_key="quoted:1",
            extracted={
                "proposed_stage": "interview_1",
                "company_name": "示例云科技",
                "job_title": "数据工程师",
                "job_code": "SYN-101",
                "event_date": "2026-08-20",
                "scheduled_date": "2026-08-25",
                "review_reasons": ["quoted_only_signal"],
            },
        )
    assert candidate is not None
    assert candidate.state == "pending"
    assert "quoted_only_signal" in candidate.review_reasons
    assert candidate.confidence < 90
    assert event is None
