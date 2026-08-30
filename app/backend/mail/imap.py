"""Read-only IMAPS connector for QQ Mail and NetEase 163 Mail."""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Literal

from .parsing import (
    MAX_HEADER_BYTES,
    MAX_TRANSFER_BYTES,
    DecodedText,
    MailContentError,
    ParsedHeader,
    decode_body_part,
    parse_header_block,
    select_body_part,
    trim_quoted_reply,
)

ImapProvider = Literal["qq", "163"]

_ENDPOINTS: dict[ImapProvider, str] = {
    "qq": "imap.qq.com",
    "163": "imap.163.com",
}
_HEADER_QUERY = (
    "BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)]"
    f"<0.{MAX_HEADER_BYTES + 1}>"
)
_HEADER_BATCH_SIZE = 100
MAX_SCAN_MESSAGES = 5000


class ImapConnectorError(RuntimeError):
    """An IMAP failure with a safe, non-sensitive public error code."""


@dataclass(frozen=True, slots=True)
class ImapCursor:
    uidvalidity: int
    last_uid: int


@dataclass(frozen=True, slots=True)
class ImapMessageHeader:
    uid: int
    internal_date: datetime | None
    message_size: int | None
    header: ParsedHeader


@dataclass(frozen=True, slots=True)
class ImapSkippedMessage:
    uid: int
    reason: str


@dataclass(frozen=True, slots=True)
class ImapScanResult:
    messages: tuple[ImapMessageHeader, ...]
    skipped: tuple[ImapSkippedMessage, ...]
    uidvalidity: int
    snapshot_uid: int
    cursor_reset: bool

    @property
    def proposed_cursor(self) -> ImapCursor:
        """Cursor to persist only after every result has been durably handled."""

        return ImapCursor(self.uidvalidity, self.snapshot_uid)


@dataclass(frozen=True, slots=True)
class ImapFetchedBody:
    uid: int
    text: str
    content_type: str
    charset: str
    used_charset_fallback: bool
    quoted_tail_trimmed: bool
    quoted_only: bool = False


ClientFactory = Callable[..., Any]


def secure_ssl_context() -> ssl.SSLContext:
    """Return a verifying TLS context with no legacy protocol fallback."""

    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def _default_client_factory(host: str, **kwargs: Any) -> Any:
    try:
        from imapclient import IMAPClient
    except ImportError as exc:
        raise ImapConnectorError("imap_dependency_missing") from exc
    return IMAPClient(host, **kwargs)


class ImapConnector:
    """A short-lived, UID-only IMAP session.

    The connector deliberately exposes no mutation primitive.  It uses EXAMINE
    and BODY.PEEK, and ends a selected session with UNSELECT/LOGOUT rather than
    CLOSE, so polling cannot mark messages read or expunge deleted mail.
    """

    def __init__(
        self,
        provider: ImapProvider,
        username: str,
        authorization_code: str,
        *,
        client_factory: ClientFactory | None = None,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float = 30.0,
        app_name: str = "CareerApplicationAssistant",
        app_version: str = "0.1.0",
    ) -> None:
        if provider not in _ENDPOINTS:
            raise ValueError("unsupported_imap_provider")
        self.provider = provider
        self._username = username
        self._authorization_code = authorization_code
        self._factory = client_factory or _default_client_factory
        self._ssl_context = ssl_context or secure_ssl_context()
        self._timeout = timeout
        self._app_name = app_name
        self._app_version = app_version
        self._client: Any | None = None
        self._selected = False

    @property
    def host(self) -> str:
        return _ENDPOINTS[self.provider]

    def __enter__(self) -> ImapConnector:
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        del exc_type, exc, traceback
        self.disconnect()

    def connect(self) -> None:
        if self._client is not None:
            return
        client: Any | None = None
        try:
            client = self._factory(
                self.host,
                port=993,
                ssl=True,
                ssl_context=self._ssl_context,
                timeout=self._timeout,
            )
            client.login(self._username, self._authorization_code)
            if self.provider == "163":
                identity = getattr(client, "id_", None)
                if identity is None:
                    raise ImapConnectorError("imap_id_command_unavailable")
                identity({"name": self._app_name, "version": self._app_version})
        except ImapConnectorError:
            try:
                if client is not None:
                    client.logout()
            except Exception:
                pass
            raise
        except Exception as exc:
            try:
                if client is not None:
                    client.logout()
            except Exception:
                pass
            raise ImapConnectorError("imap_auth_or_connection_failed") from exc
        if client is None:  # defensive for malformed injected factories
            raise ImapConnectorError("imap_client_missing")
        self._client = client

    def disconnect(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        if self._selected:
            try:
                unselect = getattr(client, "unselect_folder", None)
                if unselect is not None:
                    unselect()
            except Exception:
                pass
        self._selected = False
        try:
            client.logout()
        except Exception:
            pass

    def scan_headers(
        self,
        cursor: ImapCursor | None,
        *,
        since: datetime | date | None = None,
        reset_since: datetime | date | None = None,
        now: datetime | None = None,
        cancel_event: Any | None = None,
    ) -> ImapScanResult:
        """Fetch a finite UID snapshot of header-only data.

        With no cursor and no ``since``, existing mail is intentionally skipped
        (the "new mail only" policy).  A UIDVALIDITY change triggers a bounded
        24-hour overlap unless the caller supplies a larger backfill date.
        """

        client = self._require_client()
        status = self._select_inbox(client)
        uidvalidity = _required_status_int(status, "UIDVALIDITY")
        uidnext = _required_status_int(status, "UIDNEXT")
        snapshot_uid = max(uidnext - 1, 0)
        cursor_reset = cursor is not None and cursor.uidvalidity != uidvalidity

        effective_since = since
        if cursor_reset:
            effective_since = reset_since or effective_since
        if cursor_reset and effective_since is None:
            reference = now or datetime.now(timezone.utc)
            effective_since = reference - timedelta(hours=24)

        if cursor is None and effective_since is None:
            return ImapScanResult((), (), uidvalidity, snapshot_uid, False)
        if snapshot_uid == 0:
            return ImapScanResult((), (), uidvalidity, 0, cursor_reset)

        if cursor is not None and not cursor_reset and effective_since is None:
            start_uid = max(cursor.last_uid + 1, 1)
            if start_uid > snapshot_uid:
                return ImapScanResult((), (), uidvalidity, snapshot_uid, False)
            criteria: list[Any] = ["UID", f"{start_uid}:{snapshot_uid}"]
        else:
            backfill_date = _coerce_date(effective_since)
            if backfill_date is None:
                raise ImapConnectorError("imap_backfill_date_missing")
            criteria = ["SINCE", backfill_date, "UID", f"1:{snapshot_uid}"]

        if cancel_event is not None and cancel_event.is_set():
            raise ImapConnectorError("imap_operation_cancelled")
        try:
            found = client.search(criteria)
        except Exception as exc:
            raise ImapConnectorError("imap_search_failed") from exc
        uids = sorted({uid for item in found if (uid := _safe_int(item)) is not None and 0 < uid <= snapshot_uid})
        if len(uids) > MAX_SCAN_MESSAGES:
            uids = uids[:MAX_SCAN_MESSAGES]
            snapshot_uid = uids[-1]

        messages: list[ImapMessageHeader] = []
        skipped: list[ImapSkippedMessage] = []
        for offset in range(0, len(uids), _HEADER_BATCH_SIZE):
            if cancel_event is not None and cancel_event.is_set():
                raise ImapConnectorError("imap_operation_cancelled")
            batch = uids[offset : offset + _HEADER_BATCH_SIZE]
            try:
                fetched = client.fetch(batch, ["UID", "INTERNALDATE", "RFC822.SIZE", _HEADER_QUERY])
            except Exception as exc:
                raise ImapConnectorError("imap_header_fetch_failed") from exc
            for uid in batch:
                try:
                    record = _find_uid_record(fetched, uid)
                except ImapConnectorError as exc:
                    if str(exc) != "imap_fetch_record_missing":
                        raise
                    skipped.append(ImapSkippedMessage(uid, "mail_header_missing"))
                    continue
                raw_header = _find_record_value(record, "BODY[HEADER.FIELDS")
                if not isinstance(raw_header, bytes):
                    skipped.append(ImapSkippedMessage(uid, "mail_header_missing"))
                    continue
                if len(raw_header) > MAX_HEADER_BYTES:
                    skipped.append(ImapSkippedMessage(uid, "mail_header_too_large"))
                    continue
                try:
                    parsed = parse_header_block(raw_header)
                except MailContentError as exc:
                    skipped.append(ImapSkippedMessage(uid, str(exc)))
                    continue
                messages.append(
                    ImapMessageHeader(
                        uid=uid,
                        internal_date=_record_datetime(record, "INTERNALDATE"),
                        message_size=_record_int(record, "RFC822.SIZE"),
                        header=parsed,
                    )
                )
        return ImapScanResult(tuple(messages), tuple(skipped), uidvalidity, snapshot_uid, cursor_reset)

    def fetch_body(self, uid: int) -> ImapFetchedBody | None:
        """Fetch and decode only the selected non-attachment MIME text part."""

        if uid <= 0:
            raise ValueError("uid_must_be_positive")
        client = self._require_client()
        if not self._selected:
            self._select_inbox(client)
        try:
            structure_response = client.fetch([uid], ["UID", "BODYSTRUCTURE"])
        except Exception as exc:
            raise ImapConnectorError("imap_bodystructure_fetch_failed") from exc
        record = _find_uid_record(structure_response, uid)
        structure = _find_record_value(record, "BODYSTRUCTURE", exact=True)
        try:
            part = select_body_part(structure)
        except MailContentError as exc:
            raise ImapConnectorError(str(exc)) from exc
        if part is None:
            return None
        if part.size is not None and part.size > MAX_TRANSFER_BYTES:
            raise ImapConnectorError("mail_body_transfer_too_large")

        query = f"BODY.PEEK[{part.section}]<0.{MAX_TRANSFER_BYTES + 1}>"
        try:
            body_response = client.fetch([uid], ["UID", query])
        except Exception as exc:
            raise ImapConnectorError("imap_body_fetch_failed") from exc
        body_record = _find_uid_record(body_response, uid)
        raw = _find_record_value(body_record, f"BODY[{part.section}]", exact=True)
        if not isinstance(raw, bytes):
            raise ImapConnectorError("imap_body_missing")
        try:
            decoded: DecodedText = decode_body_part(
                raw,
                content_type=part.content_type,
                charset=part.charset,
                transfer_encoding=part.transfer_encoding,
            )
            trimmed = trim_quoted_reply(decoded.text)
        except MailContentError as exc:
            raise ImapConnectorError(str(exc)) from exc
        return ImapFetchedBody(
            uid=uid,
            text=trimmed.text,
            content_type=part.content_type,
            charset=decoded.charset,
            used_charset_fallback=decoded.used_fallback,
            quoted_tail_trimmed=trimmed.trimmed,
            quoted_only=trimmed.quoted_only,
        )

    def _require_client(self) -> Any:
        if self._client is None:
            raise ImapConnectorError("imap_not_connected")
        return self._client

    def _select_inbox(self, client: Any) -> Any:
        try:
            status = client.select_folder("INBOX", readonly=True)
        except Exception as exc:
            raise ImapConnectorError("imap_examine_failed") from exc
        self._selected = True
        return status


def _coerce_date(value: datetime | date | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value


def _status_value(status: Any, name: str) -> Any:
    if not isinstance(status, dict):
        return None
    for key in (name, name.encode("ascii")):
        if key in status:
            return status[key]
    return None


def _required_status_int(status: Any, name: str) -> int:
    value = _safe_int(_status_value(status, name))
    if value is None or value < 0:
        raise ImapConnectorError(f"imap_{name.lower()}_missing")
    return value


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_uid_record(response: Any, uid: int) -> dict[Any, Any]:
    if not isinstance(response, dict):
        raise ImapConnectorError("imap_fetch_response_invalid")
    direct = response.get(uid)
    if isinstance(direct, dict):
        return direct
    for record in response.values():
        if isinstance(record, dict) and _record_int(record, "UID") == uid:
            return record
    raise ImapConnectorError("imap_fetch_record_missing")


def _key_text(key: Any) -> str:
    if isinstance(key, bytes):
        return key.decode("ascii", errors="ignore").upper()
    return str(key).upper()


def _find_record_value(record: dict[Any, Any], name: str, *, exact: bool = False) -> Any:
    normalized = name.upper()
    for key, value in record.items():
        key_name = _key_text(key)
        exact_match = key_name == normalized or key_name.startswith(f"{normalized}<")
        if (exact and exact_match) or (not exact and key_name.startswith(normalized)):
            return value
    return None


def _record_int(record: dict[Any, Any], name: str) -> int | None:
    return _safe_int(_find_record_value(record, name, exact=True))


def _record_datetime(record: dict[Any, Any], name: str) -> datetime | None:
    value = _find_record_value(record, name, exact=True)
    return value if isinstance(value, datetime) else None
