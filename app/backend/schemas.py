"""Pydantic schemas: strict, JSON-only, no extra fields."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .clock import today_date
from .errors import ApiError, CODE_VALIDATION, validation_error

DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
TIME_RE = r"^\d{2}:\d{2}$"

STAGES = (
    "pending_review",
    "applied",
    "assessment",
    "interview_1",
    "interview_2",
    "interview_3",
    "interview_hr",
    "offer",
    "rejected",
    "withdrawn",
)
EVENT_SOURCES = ("agent_fill", "user_confirmation", "email_extract", "manual_ui")
MODES = ("online", "offline", "phone", "unknown")
APPLICATION_TYPES = ("实习", "校招", "社招", "其他")
ApplicationType = Literal["实习", "校招", "社招", "其他"]


def _check_date(value: str | None, name: str) -> str | None:
    if value is None or value == "":
        return None
    if not __import__("re").match(DATE_RE, value):
        raise ValueError(f"{name} must be ISO YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} is not a valid calendar date")
    return value


def _check_completed_date(value: str | None) -> str | None:
    checked = _check_date(value, "completed_date")
    if checked is not None and checked > today_date():
        raise ValueError("completed_date must not be in the future")
    return checked


def _check_timestamp(value: str, name: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{name} must be a timestamp")
    try:
        datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO timestamp")
    return candidate


def _required_text(value: str | None, name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{name} must not be empty")
    return value.strip()


def _check_time(value: str | None, name: str) -> str | None:
    if value is None or value == "":
        return None
    import re

    if not re.match(TIME_RE, value):
        raise ValueError(f"{name} must be ISO HH:mm")
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError(f"{name} is out of range")
    if value == "00:00":
        raise ValueError(f"{name} must not use the 00:00 sentinel; leave it empty instead")
    return value


class BaseOut(BaseModel):
    model_config = {"protected_namespaces": ()}


class ApplicationBase(BaseOut):
    id: int
    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    job_code: str | None = Field(default=None, max_length=200)
    application_type: ApplicationType | None = None
    location: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=100)
    job_url: str | None = Field(default=None, max_length=2000)
    current_status: str
    filled_at: str | None = None
    submitted_at: str | None = None
    next_action: str | None = Field(default=None, max_length=500)
    next_action_date: str | None = None
    notes: str | None = Field(default=None, max_length=1000)
    created_at: str
    updated_at: str
    archived_at: str | None = None
    latest_event: dict | None = None


class CreateApplication(BaseModel):
    model_config = {"extra": "forbid"}

    company_name: str = Field(min_length=1, max_length=200)
    job_title: str = Field(min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    job_code: str | None = Field(default=None, max_length=200)
    application_type: ApplicationType | None = None
    location: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=100)
    job_url: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=500)
    next_action_date: str | None = None
    notes: str | None = Field(default=None, max_length=1000)
    event_date: str = Field(min_length=10, max_length=10)

    _date = field_validator("next_action_date")(classmethod(lambda _cls, v: _check_date(v, "next_action_date")))
    _event_date = field_validator("event_date")(classmethod(lambda _cls, v: _check_date(v, "event_date") or v))

    @field_validator("company_name", "job_title")
    @classmethod
    def _required_names(cls, value: str, info) -> str:
        return _required_text(value, info.field_name)


class PatchApplication(BaseModel):
    model_config = {"extra": "forbid"}

    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    job_title: str | None = Field(default=None, min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    job_code: str | None = Field(default=None, max_length=200)
    application_type: ApplicationType | None = None
    location: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=100)
    job_url: str | None = Field(default=None, max_length=2000)
    next_action: str | None = Field(default=None, max_length=500)
    next_action_date: str | None = None
    notes: str | None = Field(default=None, max_length=1000)

    _date = field_validator("next_action_date")(classmethod(lambda _cls, v: _check_date(v, "next_action_date")))

    @field_validator("company_name", "job_title")
    @classmethod
    def _required_names(cls, value: str | None, info) -> str:
        return _required_text(value, info.field_name)


class EventOut(BaseOut):
    id: int
    application_id: int
    stage: str
    event_date: str
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    deadline_date: str | None = None
    deadline_time: str | None = None
    completed_date: str | None = None
    timezone: str
    mode: str | None = None
    location: str | None = None
    note: str | None = None
    source: str
    created_at: str
    updated_at: str


class CreateEvent(BaseModel):
    model_config = {"extra": "forbid"}

    stage: str
    event_date: str
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    deadline_date: str | None = None
    deadline_time: str | None = None
    completed_date: str | None = None
    timezone: str = "Asia/Shanghai"
    mode: str | None = None
    location: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=500)
    source: str = "manual_ui"

    _ed = field_validator("event_date")(classmethod(lambda _cls, v: _check_date(v, "event_date") or v))
    _sd = field_validator("scheduled_date")(classmethod(lambda _cls, v: _check_date(v, "scheduled_date")))
    _st = field_validator("scheduled_time")(classmethod(lambda _cls, v: _check_time(v, "scheduled_time")))
    _dd = field_validator("deadline_date")(classmethod(lambda _cls, v: _check_date(v, "deadline_date")))
    _dt = field_validator("deadline_time")(classmethod(lambda _cls, v: _check_time(v, "deadline_time")))
    _cd = field_validator("completed_date")(classmethod(lambda _cls, v: _check_completed_date(v)))

    @field_validator("stage")
    @classmethod
    def _stage(cls, value: str) -> str:
        if value not in STAGES:
            raise ValueError("Unknown stage.")
        return value

    def validate_stage_rules(self) -> None:
        if self.stage in ("interview_1", "interview_2", "interview_3", "interview_hr"):
            if not self.scheduled_date:
                raise validation_error("Interview stages require scheduled_date.")
        if self.stage == "assessment" and not (self.scheduled_date or self.deadline_date):
            raise validation_error("Assessment requires scheduled_date or deadline_date.")
        if self.scheduled_time and not self.scheduled_date:
            raise validation_error("scheduled_time requires scheduled_date.")
        if self.deadline_time and not self.deadline_date:
            raise validation_error("deadline_time requires deadline_date.")
        if self.completed_date and self.stage not in (
            "assessment",
            "interview_1",
            "interview_2",
            "interview_3",
            "interview_hr",
        ):
            raise validation_error("completed_date is only valid for assessment or interview stages.")
        if self.stage == "applied" and self.source != "user_confirmation":
            raise validation_error("Applied events require explicit user_confirmation.")
        if self.source not in EVENT_SOURCES:
            raise validation_error("Unknown event source.")
        if self.mode is not None and self.mode not in MODES:
            raise validation_error("Unknown interview mode.")


class PatchEvent(BaseModel):
    model_config = {"extra": "forbid"}

    event_date: str | None = None
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    deadline_date: str | None = None
    deadline_time: str | None = None
    completed_date: str | None = None
    timezone: str | None = None
    mode: str | None = None
    location: str | None = Field(default=None, max_length=300)
    note: str | None = Field(default=None, max_length=500)

    _ed = field_validator("event_date")(classmethod(lambda _cls, v: _check_date(v, "event_date")))
    _sd = field_validator("scheduled_date")(classmethod(lambda _cls, v: _check_date(v, "scheduled_date")))
    _st = field_validator("scheduled_time")(classmethod(lambda _cls, v: _check_time(v, "scheduled_time")))
    _dd = field_validator("deadline_date")(classmethod(lambda _cls, v: _check_date(v, "deadline_date")))
    _dt = field_validator("deadline_time")(classmethod(lambda _cls, v: _check_time(v, "deadline_time")))
    _cd = field_validator("completed_date")(classmethod(lambda _cls, v: _check_completed_date(v)))


class AgentFillCompleted(BaseModel):
    model_config = {"extra": "forbid"}

    company_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    job_code: str | None = Field(default=None, max_length=200)
    application_type: ApplicationType | None = None
    location: str | None = Field(default=None, max_length=200)
    source: str | None = Field(default=None, max_length=100)
    job_url: str | None = Field(default=None, max_length=2000)
    filled_at: str = Field(min_length=1, max_length=40)

    @field_validator("filled_at")
    @classmethod
    def _filled(cls, value: str) -> str:
        return _check_timestamp(value, "filled_at")


class AgentMatch(BaseModel):
    model_config = {"extra": "forbid"}

    application_id: int | None = Field(default=None, gt=0)
    company_name: str | None = Field(default=None, max_length=200)
    job_title: str | None = Field(default=None, max_length=200)
    job_code: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    job_url: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _has_match_value(self) -> "AgentMatch":
        values = self.model_dump(exclude_none=True)
        if not any(value for value in values.values() if str(value).strip()):
            raise ValueError("match needs at least one non-empty value.")
        return self


class AgentStatusUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    match: AgentMatch
    event: CreateEvent


class BoardCounts(BaseModel):
    pending_review: int = 0
    applied: int = 0
    assessment: int = 0
    interview: int = 0
    ended: int = 0


class ListResponse(BaseModel):
    items: list[ApplicationBase]
    total: int
    page: int
    page_size: int
    counts: BoardCounts
    options: dict[str, list[str]]
