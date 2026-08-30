"""Deterministic bilingual recruitment-mail classification and extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .parsing import trim_quoted_reply

MailStage = Literal[
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
]

SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class ExtractedMailEvent:
    stage: MailStage | None
    event_date: str
    scheduled_date: str | None
    scheduled_time: str | None
    deadline_date: str | None
    deadline_time: str | None
    timezone: str
    company_name: str | None
    job_title: str | None
    confidence: int
    reasons: tuple[str, ...]
    stage_candidates: tuple[MailStage, ...]
    ambiguous_date: bool
    negative_signal: bool
    # Match hints are transient.  They help the service match an existing local
    # application but must not be copied to the persisted candidate payload.
    job_code: str | None = None
    job_url: str | None = None
    location: str | None = None
    mode: Literal["online", "offline", "phone", "unknown"] = "unknown"


_STAGE_PATTERNS: tuple[tuple[MailStage, tuple[re.Pattern[str], ...]], ...] = (
    (
        "withdrawn",
        (
            re.compile(r"(?:申请|投递).{0,12}(?:已成功)?撤回"),
            re.compile(r"\b(?:your\s+)?application\s+(?:has\s+been\s+|was\s+)?withdrawn\b", re.I),
        ),
    ),
    (
        "rejected",
        (
            re.compile(r"(?:申请|应聘|面试).{0,24}(?:未通过|不通过|未获通过|未能进入|暂不匹配|不予录用)"),
            re.compile(r"很遗憾.{0,50}(?:未能|不能|无法|没有通过|不匹配)"),
            re.compile(r"\bwe regret to inform\b", re.I),
            re.compile(r"\b(?:will not|won't|not)\s+(?:be\s+)?mov(?:e|ing)\s+forward\b", re.I),
            re.compile(r"\b(?:application|candidacy).{0,30}(?:unsuccessful|not selected|declined)\b", re.I),
        ),
    ),
    (
        "offer",
        (
            re.compile(r"(?:正式)?录用通知|确认录用|发放\s*[Oo]ffer|[Oo]ffer\s*通知"),
            re.compile(r"\b(?:employment\s+offer|offer\s+letter|pleased\s+to\s+offer\s+you)\b", re.I),
        ),
    ),
    (
        "interview_hr",
        (
            re.compile(r"(?:HR|Hr|hr|人力(?:资源)?)(?:终)?面(?:试)?|面试.{0,8}(?:HR|人力(?:资源)?)"),
            re.compile(r"\b(?:hr|human resources)\s+(?:round\s+)?interview\b", re.I),
        ),
    ),
    (
        "interview_3",
        (
            re.compile(r"(?:第\s*(?:三|3)\s*(?:轮|次)\s*面试|(?:三面|3\s*面)(?:面试)?)"),
            re.compile(r"\b(?:third|3rd)\s+(?:round\s+)?interview\b", re.I),
        ),
    ),
    (
        "interview_2",
        (
            re.compile(r"(?:第\s*(?:二|2)\s*(?:轮|次)\s*面试|(?:二面|2\s*面)(?:面试)?)"),
            re.compile(r"\b(?:second|2nd)\s+(?:round\s+)?interview\b", re.I),
        ),
    ),
    (
        "interview_1",
        (
            re.compile(r"(?:第\s*(?:一|1)\s*(?:轮|次)\s*面试|(?:一面|1\s*面|初面)(?:面试)?)"),
            re.compile(r"\b(?:first|1st)\s+(?:round\s+)?interview\b", re.I),
        ),
    ),
    (
        "assessment",
        (
            re.compile(r"(?:在线|线上)?(?:测评|笔试|编程测试|性格测试|能力测试|人才测验)"),
            re.compile(r"\b(?:online\s+)?(?:assessment|coding test|written test|aptitude test|psychometric test)\b", re.I),
        ),
    ),
    (
        "applied",
        (
            re.compile(r"(?:投递|申请)(?:已经|已)?(?:成功|提交|收到|完成)|已收到.{0,12}(?:投递|申请|简历)"),
            re.compile(r"\b(?:application (?:was |has been )?(?:received|submitted)|successfully applied)\b", re.I),
        ),
    ),
    (
        "interview_unspecified",
        (
            re.compile(r"面试(?:邀请|通知|安排|确认)|邀请.{0,16}面试|参加.{0,12}面试"),
            re.compile(r"\b(?:interview invitation|invite.{0,20}interview|schedule.{0,20}interview)\b", re.I),
        ),
    ),
)

_NEGATIVE_PATTERNS = (
    re.compile(r"职位(?:推荐|订阅|周报|速递)|岗位推荐|猜你喜欢|招聘(?:周报|精选)|更多相似职位"),
    re.compile(r"\b(?:job alert|recommended jobs?|jobs? you may like|weekly jobs? digest|similar jobs?)\b", re.I),
)

_HEADER_RECRUITMENT = re.compile(
    r"面试|测评|笔试|录用|投递|应聘|职位申请|招聘|offer|interview|assessment|application|recruit|career",
    re.I,
)


def is_likely_recruitment_header(subject: str, sender: str = "") -> bool:
    """High-recall header gate; a negative digest alone is not fetched."""

    text = f"{subject}\n{sender}"[:4096]
    if any(pattern.search(subject) for pattern in _NEGATIVE_PATTERNS):
        return False
    stages = _detect_stages(text)
    if stages:
        return True
    return bool(_HEADER_RECRUITMENT.search(text))


def classify_and_extract(
    *,
    subject: str,
    sender: str,
    received_at: datetime | str,
    body: str = "",
    charset_fallback: bool = False,
    quoted_only: bool = False,
    quoted_tail_trimmed: bool = False,
) -> ExtractedMailEvent:
    """Classify one message without model calls, network access, or guessing."""

    del sender  # sender domains are deliberately not used to infer a company
    received = _coerce_received_at(received_at)
    trimmed = trim_quoted_reply(body)
    quote_only_signal = quoted_only or trimmed.quoted_only
    text = f"{subject}\n{trimmed.text}"[: 512 * 1024]
    negative = any(pattern.search(subject) for pattern in _NEGATIVE_PATTERNS)
    stages = _detect_stages(text)

    # Digest subjects suppress all body hits: quoted history and promotional
    # snippets frequently contain transactional vocabulary.
    if negative:
        stages = []
    if any(stage.startswith("interview_") and stage != "interview_unspecified" for stage in stages):
        stages = [stage for stage in stages if stage != "interview_unspecified"]

    stage = stages[0] if stages else None
    company = _extract_company(text)
    job_title = _extract_job_title(text)
    job_code = _extract_label(text, ("职位编号", "岗位编号", "职位ID", "Job ID", "Req ID", "Requisition ID"), 80)
    location = _extract_label(text, ("工作地点", "Job Location", "Location"), 160)
    job_url = _extract_job_url(text)
    mode = _extract_mode(text) if stage and stage.startswith("interview_") else "unknown"

    scheduled_date: str | None = None
    scheduled_time: str | None = None
    deadline_date: str | None = None
    deadline_time: str | None = None
    ambiguous_date = False
    if stage == "assessment" or (stage and stage.startswith("interview_")):
        temporal = _extract_temporal(text, received, stage)
        scheduled_date = temporal.scheduled_date
        scheduled_time = temporal.scheduled_time
        deadline_date = temporal.deadline_date
        deadline_time = temporal.deadline_time
        ambiguous_date = temporal.ambiguous

    reasons: list[str] = []
    confidence = 0
    if stage:
        confidence += 35
        reasons.append("stage_explicit")
    if company and job_title:
        confidence += 35
        reasons.append("company_and_job_explicit")
    elif company or job_title:
        confidence += 20
        reasons.append("partial_job_identity")

    needs_schedule = bool(stage == "assessment" or (stage and stage.startswith("interview_")))
    has_required_date = bool(
        (stage == "assessment" and (scheduled_date or deadline_date))
        or (stage and stage.startswith("interview_") and scheduled_date)
    )
    if stage and (has_required_date or not needs_schedule):
        confidence += 20
        reasons.append("required_date_present" if needs_schedule else "date_not_required")

    consistent = bool(
        stage
        and len(stages) == 1
        and not ambiguous_date
        and not negative
        and not quote_only_signal
    )
    if consistent:
        confidence += 10
        reasons.append("signals_consistent")
    if len(stages) > 1:
        confidence -= 25
        reasons.append("conflicting_stages")
    if ambiguous_date:
        confidence -= 20
        reasons.append("ambiguous_date")
    if charset_fallback:
        confidence -= 10
        reasons.append("charset_fallback")
    if trimmed.trimmed or quoted_tail_trimmed:
        reasons.append("quoted_tail_removed")
    if quote_only_signal:
        confidence -= 40
        reasons.append("quoted_only_signal")
    if negative:
        confidence -= 30
        reasons.append("job_digest_signal")
    if stage is None:
        confidence = 0
        reasons.append("stage_missing")

    return ExtractedMailEvent(
        stage=stage,
        event_date=received.astimezone(SHANGHAI).date().isoformat(),
        scheduled_date=scheduled_date,
        scheduled_time=scheduled_time,
        deadline_date=deadline_date,
        deadline_time=deadline_time,
        timezone="Asia/Shanghai",
        company_name=company,
        job_title=job_title,
        confidence=max(0, min(100, confidence)),
        reasons=tuple(reasons),
        stage_candidates=tuple(stages),
        ambiguous_date=ambiguous_date,
        negative_signal=negative,
        job_code=job_code,
        job_url=job_url,
        location=location,
        mode=mode,
    )


def _detect_stages(text: str) -> list[MailStage]:
    result: list[MailStage] = []
    for stage, patterns in _STAGE_PATTERNS:
        if any(pattern.search(text) for pattern in patterns):
            result.append(stage)
    return result


def _coerce_received_at(value: datetime | str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("received_at_must_be_iso_timestamp") from exc
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value


_LABEL_TEMPLATE = r"(?im)^\s*(?:{labels})\s*[:：]\s*([^\r\n]{{1,{limit}}})\s*$"
_CONTACT_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_CONTACT_URL_RE = re.compile(r"(?:https?://|www\.|mailto:|tel:)", re.I)
_CONTACT_LABEL_RE = re.compile(r"(?:联系人|联系电话|手机|微信|wechat|contact|phone|e-?mail)\s*[:：]", re.I)
_CONTACT_NUMBER_RE = re.compile(r"(?<!\d)\+?[\d() .-]{9,}\d(?!\d)")


def contains_private_contact_info(value: str) -> bool:
    """Return whether an extracted label appears to contain private contact data."""

    if _CONTACT_EMAIL_RE.search(value) or _CONTACT_URL_RE.search(value):
        return True
    if _CONTACT_LABEL_RE.search(value):
        return True
    return any(
        len(re.sub(r"\D", "", match.group(0))) >= 10
        for match in _CONTACT_NUMBER_RE.finditer(value)
    )


def _extract_label(text: str, labels: tuple[str, ...], limit: int) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(_LABEL_TEMPLATE.format(labels=label_pattern, limit=limit), text)
    if not match:
        return None
    value = _clean_field(match.group(1), limit)
    if not value or value.lower().startswith(("http://", "https://")):
        return None
    return value


def _extract_company(text: str) -> str | None:
    labelled = _extract_label(text, ("公司", "公司名称", "企业", "Company", "Employer"), 160)
    if labelled:
        return labelled
    patterns = (
        re.compile(r"感谢您(?:申请|投递)\s*[“\"《]?([^，。；：\n]{2,80}?公司)[”\"》]?(?:的|\s)"),
        re.compile(r"\byour application (?:to|with)\s+([A-Z][^\n,.]{1,79})", re.I),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return _clean_field(match.group(1), 160)
    return None


def _extract_job_title(text: str) -> str | None:
    labelled = _extract_label(text, ("职位", "岗位", "应聘职位", "申请职位", "Job Title", "Position", "Role"), 160)
    if labelled:
        return labelled
    patterns = (
        re.compile(r"您(?:所)?申请的\s*[“\"《]?([^，。；：\n]{2,100}?)[”\"》]?\s*(?:岗位|职位)"),
        re.compile(r"\bapplication for (?:the )?(?:position|role) of\s+([^\n,.]{2,100})", re.I),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return _clean_field(match.group(1), 160)
    return None


def _clean_field(value: str, limit: int) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\"'“”‘’《》:：,，。;；")[:limit]
    if (
        not cleaned
        or any(char in cleaned for char in "<>\x00")
        or contains_private_contact_info(cleaned)
    ):
        return None
    return cleaned


_URL_LABEL = re.compile(r"(?im)^\s*(?:职位链接|岗位链接|Job URL|Job Link)\s*[:：]\s*(https://[^\s<>]+)")
_DISALLOWED_JOB_URL_HOSTS = (
    "zoom.us",
    "teams.microsoft.com",
    "meeting.tencent.com",
    "voovmeeting.com",
)


def _extract_job_url(text: str) -> str | None:
    match = _URL_LABEL.search(text)
    if not match:
        return None
    value = match.group(1).rstrip(".,，。;；)）]")[:2000]
    try:
        host = (urlsplit(value).hostname or "").lower()
    except ValueError:
        return None
    if not host or any(host == item or host.endswith(f".{item}") for item in _DISALLOWED_JOB_URL_HOSTS):
        return None
    return value


def _extract_mode(text: str) -> Literal["online", "offline", "phone", "unknown"]:
    if re.search(r"线上|在线视频|视频面试|腾讯会议|飞书会议|Zoom|Teams|video interview|online interview", text, re.I):
        return "online"
    if re.search(r"电话面试|电话沟通|phone interview|telephone interview", text, re.I):
        return "phone"
    if re.search(r"现场面试|线下面试|到访|onsite interview|in-person interview", text, re.I):
        return "offline"
    return "unknown"


@dataclass(frozen=True, slots=True)
class _TemporalResult:
    scheduled_date: str | None
    scheduled_time: str | None
    deadline_date: str | None
    deadline_time: str | None
    ambiguous: bool


_DEADLINE_WORDS = re.compile(r"截止|最晚|之前完成|有效期|deadline|complete by|due(?: date)?", re.I)
_DATE_CUE = re.compile(
    r"20\d{2}[年./-]\d{1,2}[月./-]\d{1,2}日?|\d{1,2}月\d{1,2}日|"
    r"今天|明天|后天|下周[一二三四五六日天]|today|tomorrow|next\s+(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,\s*20\d{2})?",
    re.I,
)
_AMBIGUOUS_SLASH = re.compile(r"(?<!\d)(0?[1-9]|1[0-2])/(0?[1-9]|1[0-2])(?:/(?:\d{2}|\d{4}))?(?!\d)")


def _extract_temporal(text: str, received: datetime, stage: MailStage) -> _TemporalResult:
    del stage
    scheduled: list[tuple[date, str | None]] = []
    deadlines: list[tuple[date, str | None]] = []
    ambiguous = False
    segments = re.split(r"[\r\n]+|(?<=[。；;])", text)
    for segment in segments:
        if not segment.strip():
            continue
        if _AMBIGUOUS_SLASH.search(segment) and not re.search(r"20\d{2}/", segment):
            ambiguous = True
            continue
        for match in _DATE_CUE.finditer(segment):
            parsed = _parse_date_phrase(match.group(0), received)
            if parsed is None:
                continue
            explicit_time = _extract_time(segment)
            item = (parsed, explicit_time)
            if _DEADLINE_WORDS.search(segment):
                deadlines.append(item)
            else:
                scheduled.append(item)

    scheduled_value, scheduled_time, scheduled_conflict = _single_temporal(scheduled)
    deadline_value, deadline_time, deadline_conflict = _single_temporal(deadlines)
    ambiguous = ambiguous or scheduled_conflict or deadline_conflict
    if ambiguous:
        if scheduled_conflict:
            scheduled_value = scheduled_time = None
        if deadline_conflict:
            deadline_value = deadline_time = None
    return _TemporalResult(
        scheduled_date=scheduled_value,
        scheduled_time=scheduled_time,
        deadline_date=deadline_value,
        deadline_time=deadline_time,
        ambiguous=ambiguous,
    )


def _single_temporal(items: list[tuple[date, str | None]]) -> tuple[str | None, str | None, bool]:
    if not items:
        return None, None, False
    unique = {(item.isoformat(), time) for item, time in items}
    distinct_dates = {item[0] for item in unique}
    if len(distinct_dates) > 1:
        return None, None, True
    date_value = next(iter(distinct_dates))
    explicit_times = {item[1] for item in unique if item[1] is not None}
    if len(explicit_times) > 1:
        return date_value, None, True
    return date_value, next(iter(explicit_times), None), False


def _parse_date_phrase(phrase: str, received: datetime) -> date | None:
    settings = {
        "RELATIVE_BASE": received.astimezone(SHANGHAI).replace(tzinfo=None),
        "TIMEZONE": "Asia/Shanghai",
        "RETURN_AS_TIMEZONE_AWARE": True,
        "PREFER_DATES_FROM": "future",
        "DATE_ORDER": "YMD",
        "STRICT_PARSING": True,
    }
    try:
        import dateparser
    except ImportError:
        parsed = None
    else:
        parsed = dateparser.parse(phrase, languages=["zh", "en"], settings=settings)
    if parsed is not None:
        return parsed.astimezone(SHANGHAI).date() if parsed.tzinfo else parsed.date()
    return _fallback_date_parse(phrase, received.astimezone(SHANGHAI).date())


def _fallback_date_parse(phrase: str, base: date) -> date | None:
    normalized = phrase.strip().lower()
    relative_days = {"今天": 0, "明天": 1, "后天": 2, "today": 0, "tomorrow": 1}
    if normalized in relative_days:
        return base + timedelta(days=relative_days[normalized])
    week_match = re.fullmatch(r"下周([一二三四五六日天])", normalized)
    if week_match:
        weekday = "一二三四五六日天".index(week_match.group(1))
        weekday = min(weekday, 6)
        return base + timedelta(days=(7 - base.weekday()) + weekday)

    full = re.fullmatch(r"(20\d{2})[年./-](\d{1,2})[月./-](\d{1,2})日?", normalized)
    if full:
        return _safe_date(*(int(item) for item in full.groups()))
    month_day = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", normalized)
    if month_day:
        month, day = (int(item) for item in month_day.groups())
        candidate = _safe_date(base.year, month, day)
        if candidate is not None and candidate < base:
            candidate = _safe_date(base.year + 1, month, day)
        return candidate

    english_weekday = re.fullmatch(r"next\s+(mon|tue|wed|thu|fri|sat|sun)[a-z]*", normalized)
    if english_weekday:
        target = ("mon", "tue", "wed", "thu", "fri", "sat", "sun").index(english_weekday.group(1))
        return base + timedelta(days=(7 - base.weekday()) + target)
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_time(segment: str) -> str | None:
    english = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", segment, re.I)
    if english:
        hour = int(english.group(1)) % 12
        if english.group(3).lower() == "pm":
            hour += 12
        return _valid_time(hour, int(english.group(2) or 0))
    chinese = re.search(r"(上午|下午|晚上)?\s*(\d{1,2})(?:[:：点时](\d{2})?|点半)", segment)
    if chinese:
        period, hour_text, minute_text = chinese.groups()
        hour = int(hour_text)
        minute = 30 if "点半" in chinese.group(0) else int(minute_text or 0)
        if period in {"下午", "晚上"} and hour < 12:
            hour += 12
        if period == "上午" and hour == 12:
            hour = 0
        return _valid_time(hour, minute)
    return None


def _valid_time(hour: int, minute: int) -> str | None:
    if not (0 <= hour <= 23 and 0 <= minute <= 59) or (hour == 0 and minute == 0):
        return None
    return f"{hour:02d}:{minute:02d}"
