"""Public API models for mailbox accounts and structured mail candidates."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..schemas import STAGES, _check_date, _check_time

MailProvider = Literal["outlook", "qq", "163"]
MailConnectionMode = Literal["codex_connector", "local_imap"]
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
    connection_mode: MailConnectionMode
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


class OutlookScanWindowOut(StrictModel):
    id: str
    kind: Literal["live", "backfill"]
    received_from: datetime
    received_before: datetime
    from_index: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)


class OutlookRunStartOut(StrictModel):
    state: Literal["started", "busy", "paused"]
    run_id: str | None = None
    lease_expires_at: datetime | None = None
    remaining_budget: int = Field(default=0, ge=0, le=200)
    windows: list[OutlookScanWindowOut] = Field(default_factory=list, max_length=2)


class OutlookHeaderItem(StrictModel):
    token: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    source_id: str = Field(min_length=1, max_length=2048)
    subject: str = Field(default="", max_length=4096)
    sender: str = Field(default="", max_length=4096)
    received_at: datetime

    @field_validator("received_at")
    @classmethod
    def _aware_received_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a timezone offset.")
        return value


class OutlookHeaderBatchRequest(StrictModel):
    window_id: str = Field(min_length=1, max_length=64)
    from_index: int = Field(ge=0)
    items: list[OutlookHeaderItem] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_tokens(self) -> "OutlookHeaderBatchRequest":
        tokens = [item.token for item in self.items]
        if len(tokens) != len(set(tokens)):
            raise ValueError("Header tokens must be unique within a batch.")
        return self


class OutlookBodyTokenOut(StrictModel):
    token: str
    body_token: str


class OutlookHeaderBatchOut(StrictModel):
    body_tokens: list[OutlookBodyTokenOut]
    duplicate_count: int = Field(ge=0)
    ignored_count: int = Field(ge=0)
    remaining_budget: int = Field(ge=0, le=200)


class OutlookMessageItem(OutlookHeaderItem):
    body_token: str = Field(min_length=32, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    body: str = Field(default="", max_length=524_288)
    content_type: Literal["text", "html"] = "text"
    body_status: Literal["available", "missing", "too_large"] = "available"

    @model_validator(mode="after")
    def _bounded_body(self) -> "OutlookMessageItem":
        if len(self.body.encode("utf-8")) > 524_288:
            raise ValueError("Message body exceeds the 512 KiB UTF-8 limit.")
        if self.body_status != "available" and self.body:
            raise ValueError("Unavailable message bodies must be empty.")
        return self


class OutlookMessageBatchRequest(StrictModel):
    items: list[OutlookMessageItem] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _bounded_batch(self) -> "OutlookMessageBatchRequest":
        if sum(len(item.body.encode("utf-8")) for item in self.items) > 2 * 1024 * 1024:
            raise ValueError("Message batch exceeds the 2 MiB UTF-8 limit.")
        tokens = [item.token for item in self.items]
        if len(tokens) != len(set(tokens)):
            raise ValueError("Message tokens must be unique within a batch.")
        body_tokens = [item.body_token for item in self.items]
        if len(body_tokens) != len(set(body_tokens)):
            raise ValueError("Body tokens must be unique within a batch.")
        return self


class OutlookMessageBatchOut(StrictModel):
    accepted_count: int = Field(ge=0)
    queued_count: int = Field(ge=0)
    committed_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    ignored_count: int = Field(ge=0)


class OutlookWindowCompletion(StrictModel):
    window_id: str = Field(min_length=1, max_length=64)
    headers_processed: int = Field(ge=0, le=200)
    has_more: bool
    next_from_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _continuation_required(self) -> "OutlookWindowCompletion":
        if self.has_more and self.next_from_index is None:
            raise ValueError("A continuing window requires next_from_index.")
        if not self.has_more and self.next_from_index is not None:
            raise ValueError("A completed window must not include next_from_index.")
        return self


class OutlookRunCompleteRequest(StrictModel):
    windows: list[OutlookWindowCompletion] = Field(min_length=1, max_length=2)


class OutlookRunCompleteOut(StrictModel):
    state: Literal["completed"] = "completed"
    pending_windows: int = Field(ge=0)
    processed_headers: int = Field(ge=0, le=200)
    processed_bodies: int = Field(ge=0, le=200)


OutlookFailureCode = Literal[
    "connector_unavailable",
    "connector_auth_required",
    "inbox_unavailable",
    "list_failed",
    "fetch_failed",
    "ingest_failed",
    "scan_limit_reached",
]


class OutlookRunFailRequest(StrictModel):
    error_code: OutlookFailureCode


class OutlookRunFailOut(StrictModel):
    state: Literal["failed"] = "failed"
    error_code: OutlookFailureCode
