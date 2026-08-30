"""Public API models for mailbox accounts and structured mail candidates."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..schemas import STAGES, _check_date, _check_time

MailProvider = Literal["outlook", "qq", "163"]
HistoryWindow = Literal["new_only", "last_30_days", "last_90_days"]
MailAccountStatus = Literal[
    "disconnected", "connecting", "connected", "paused", "needs_reauth", "error"
]
MailOperationStatus = Literal["pending", "running", "succeeded", "failed"]
MailCandidateState = Literal["pending", "committed", "dismissed", "expired", "duplicate"]
ProposedMailStage = Literal[
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


class StrictModel(BaseModel):
    model_config = {"extra": "forbid", "protected_namespaces": ()}


class OutlookConnectRequest(StrictModel):
    client_id: str = Field(min_length=8, max_length=200)
    history_window: HistoryWindow = "new_only"

    @field_validator("client_id")
    @classmethod
    def _trim_client_id(cls, value: str) -> str:
        candidate = value.strip()
        if not candidate or any(char.isspace() for char in candidate):
            raise ValueError("client_id must be a single non-empty value.")
        return candidate


class ImapConnectRequest(StrictModel):
    mailbox_address: str = Field(min_length=3, max_length=320)
    authorization_code: str = Field(min_length=1, max_length=2048)
    history_window: HistoryWindow = "new_only"

    @field_validator("mailbox_address")
    @classmethod
    def _mailbox_address(cls, value: str) -> str:
        candidate = value.strip()
        if "@" not in candidate or any(char.isspace() for char in candidate):
            raise ValueError("mailbox_address must be a valid mailbox address.")
        return candidate

    @field_validator("authorization_code")
    @classmethod
    def _authorization_code(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("authorization_code must not be empty.")
        return value


class MailAccountOut(StrictModel):
    provider: MailProvider
    status: MailAccountStatus
    masked_address: str | None = None
    history_window: HistoryWindow = "new_only"
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    next_retry_at: str | None = None
    error_code: str | None = None
    pending_count: int = 0


class MailAccountsOut(StrictModel):
    items: list[MailAccountOut]
    pending_count: int = 0


class MailOperationOut(StrictModel):
    id: str
    provider: MailProvider
    kind: Literal["connect", "sync"]
    status: MailOperationStatus
    error_code: str | None = None


class MailOperationAccepted(StrictModel):
    operation_id: str
    status: Literal["pending"] = "pending"


class MailCandidateOut(StrictModel):
    id: int
    provider: MailProvider
    state: MailCandidateState
    company_name: str | None = None
    job_title: str | None = None
    proposed_stage: ProposedMailStage | None = None
    event_date: str | None = None
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    deadline_date: str | None = None
    deadline_time: str | None = None
    timezone: str = "Asia/Shanghai"
    confidence: int = Field(ge=0, le=100)
    matched_application_id: int | None = None
    review_reasons: list[str] = Field(default_factory=list)
    expires_at: str | None = None


class MailCandidateListOut(StrictModel):
    items: list[MailCandidateOut]
    total: int


class MailCandidateConfirmRequest(StrictModel):
    application_id: int = Field(gt=0)
    stage: str
    scheduled_date: str | None = None
    scheduled_time: str | None = None
    deadline_date: str | None = None
    deadline_time: str | None = None
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=100)
    confirm_personally_submitted: bool = False

    _scheduled_date = field_validator("scheduled_date")(
        classmethod(lambda _cls, value: _check_date(value, "scheduled_date"))
    )
    _scheduled_time = field_validator("scheduled_time")(
        classmethod(lambda _cls, value: _check_time(value, "scheduled_time"))
    )
    _deadline_date = field_validator("deadline_date")(
        classmethod(lambda _cls, value: _check_date(value, "deadline_date"))
    )
    _deadline_time = field_validator("deadline_time")(
        classmethod(lambda _cls, value: _check_time(value, "deadline_time"))
    )

    @field_validator("stage")
    @classmethod
    def _stage(cls, value: str) -> str:
        if value not in STAGES or value == "pending_review":
            raise ValueError("Unknown candidate stage.")
        return value

    @model_validator(mode="after")
    def _submission_confirmation(self) -> "MailCandidateConfirmRequest":
        if self.stage == "applied" and not self.confirm_personally_submitted:
            raise ValueError("Applied requires explicit personal-submission confirmation.")
        return self


class MailCandidateCommitOut(StrictModel):
    candidate: MailCandidateOut
    application: dict
    event: dict
