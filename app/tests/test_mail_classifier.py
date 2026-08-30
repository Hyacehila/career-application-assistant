from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.mail.classifier import classify_and_extract, is_likely_recruitment_header


RECEIVED = datetime(2026, 8, 30, 2, 30, tzinfo=timezone.utc)


def test_chinese_assessment_extracts_only_explicit_identity_and_deadline() -> None:
    result = classify_and_extract(
        subject="在线测评通知",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="公司：示例科技\n岗位：后端开发实习生\n请于明天 18:00 前完成在线测评，截止后链接失效。",
    )

    assert result.stage == "assessment"
    assert result.company_name == "示例科技"
    assert result.job_title == "后端开发实习生"
    assert result.deadline_date == "2026-08-31"
    assert result.deadline_time == "18:00"
    assert result.scheduled_date is None
    assert result.event_date == "2026-08-30"
    assert result.confidence == 100


def test_numbered_interview_extracts_schedule_mode_and_job_code() -> None:
    result = classify_and_extract(
        subject="第二轮面试安排",
        sender="careers@invalid",
        received_at=RECEIVED,
        body=(
            "Company: Example Labs\n"
            "Job Title: Platform Engineer\n"
            "Job ID: SYN-2048\n"
            "Your second round interview is scheduled for 2026-09-02 at 2:30 PM via Teams."
        ),
    )

    assert result.stage == "interview_2"
    assert result.scheduled_date == "2026-09-02"
    assert result.scheduled_time == "14:30"
    assert result.mode == "online"
    assert result.job_code == "SYN-2048"
    assert result.confidence == 100


@pytest.mark.parametrize(
    ("subject", "expected"),
    [
        ("Your application has been received", "applied"),
        ("Employment offer letter", "offer"),
        ("We regret to inform you about your application", "rejected"),
        ("Your application has been withdrawn", "withdrawn"),
        ("HR interview invitation", "interview_hr"),
        ("面试邀请", "interview_unspecified"),
    ],
)
def test_stage_matrix(subject: str, expected: str) -> None:
    result = classify_and_extract(
        subject=subject,
        sender="no-reply@invalid",
        received_at=RECEIVED,
    )
    assert result.stage == expected


def test_job_digest_is_negative_and_not_a_generic_interview() -> None:
    subject = "职位推荐：本周精选与面试技巧"
    assert is_likely_recruitment_header(subject) is False
    result = classify_and_extract(
        subject=subject,
        sender="digest@invalid",
        received_at=RECEIVED,
        body="猜你喜欢：软件工程师、数据分析师。",
    )
    assert result.stage is None
    assert result.negative_signal is True
    assert result.confidence == 0


def test_sender_domain_is_never_used_to_guess_company_or_job() -> None:
    result = classify_and_extract(
        subject="面试邀请",
        sender="talent@invalid",
        received_at=RECEIVED,
        body="面试时间：2026-09-03 10:00",
    )
    assert result.company_name is None
    assert result.job_title is None
    assert result.stage == "interview_unspecified"
    assert result.confidence < 90


def test_contact_details_inside_identity_labels_are_not_extracted() -> None:
    contact_address = "private-contact" + "@" + "contact.example"
    contact_number = "138" + "0000" + "0000"
    result = classify_and_extract(
        subject="第一轮面试邀请",
        sender="robot@invalid",
        received_at=RECEIVED,
        body=(
            f"公司：示例科技 联系人：{contact_address}\n"
            f"岗位：后端工程师 电话：{contact_number}\n"
            "第一轮面试时间：2026年9月3日 10:00"
        ),
    )

    assert result.company_name is None
    assert result.job_title is None


def test_ambiguous_numeric_date_requires_review() -> None:
    result = classify_and_extract(
        subject="Interview invitation",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="Company: Example Labs\nJob Title: Engineer\nYour interview is on 03/04 at 10 AM.",
    )
    assert result.stage == "interview_unspecified"
    assert result.ambiguous_date is True
    assert result.scheduled_date is None
    assert result.confidence < 90


def test_conflicting_stage_signals_are_reported_and_penalized() -> None:
    result = classify_and_extract(
        subject="在线测评与第一轮面试通知",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="公司：示例公司\n岗位：工程师\n日期：2026年9月1日",
    )
    assert set(result.stage_candidates) == {"assessment", "interview_1"}
    assert "conflicting_stages" in result.reasons
    assert result.confidence < 90


def test_quoted_old_outcome_does_not_override_current_message() -> None:
    result = classify_and_extract(
        subject="第二轮面试安排",
        sender="robot@invalid",
        received_at=RECEIVED,
        body=(
            "公司：示例公司\n岗位：工程师\n第二轮面试时间：2026年9月2日 14:00\n\n"
            "-----Original Message-----\n很遗憾，您的申请未通过。"
        ),
    )
    assert result.stage == "interview_2"
    assert result.stage_candidates == ("interview_2",)
    assert "quoted_tail_removed" in result.reasons


def test_multiple_schedule_dates_and_midnight_sentinel_stay_unset() -> None:
    result = classify_and_extract(
        subject="第一轮面试安排",
        sender="robot@invalid",
        received_at=RECEIVED,
        body=(
            "公司：示例公司\n岗位：工程师\n"
            "第一轮面试候选时间：2026年9月2日 00:00；或者 2026年9月3日 10:00。"
        ),
    )
    assert result.ambiguous_date is True
    assert result.scheduled_date is None
    assert result.scheduled_time is None


def test_charset_fallback_reduces_confidence() -> None:
    normal = classify_and_extract(
        subject="录用通知",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="公司：示例公司\n岗位：工程师",
    )
    fallback = classify_and_extract(
        subject="录用通知",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="公司：示例公司\n岗位：工程师",
        charset_fallback=True,
    )
    assert fallback.confidence == normal.confidence - 10
    assert "charset_fallback" in fallback.reasons


def test_only_explicit_labelled_job_url_is_extracted_and_meeting_url_is_rejected() -> None:
    accepted = classify_and_extract(
        subject="申请已收到",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="职位链接：https://careers.example.invalid/jobs/SYN-1",
    )
    rejected = classify_and_extract(
        subject="面试邀请",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="Job URL: https://teams.microsoft.com/l/meetup-join/synthetic",
    )
    assert accepted.job_url == "https://careers.example.invalid/jobs/SYN-1"
    assert rejected.job_url is None


def test_interview_venue_is_never_used_as_job_location_match_hint() -> None:
    venue_only = classify_and_extract(
        subject="面试邀请",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="面试地点：上海市虚构路 1 号\n面试时间：2026年9月3日 10:00",
    )
    job_location = classify_and_extract(
        subject="面试邀请",
        sender="robot@invalid",
        received_at=RECEIVED,
        body="工作地点：上海\n面试时间：2026年9月3日 10:00",
    )
    assert venue_only.location is None
    assert job_location.location == "上海"


def test_forwarded_message_is_structured_but_marked_quote_only() -> None:
    event = classify_and_extract(
        subject="Fwd: 第一轮面试邀请",
        sender="robot@invalid",
        received_at="2026-08-30T10:00:00+08:00",
        body=(
            "-----Original Message-----\n"
            "公司：示例云科技\n岗位：数据工程师\n工作地点：上海\n"
            "面试时间：2026年9月3日 10:30"
        ),
    )
    assert event.stage == "interview_1"
    assert event.company_name == "示例云科技"
    assert "quoted_only_signal" in event.reasons
    assert event.confidence < 90
