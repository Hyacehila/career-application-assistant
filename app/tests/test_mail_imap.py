from __future__ import annotations

import ssl
from threading import Event
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.mail.imap import ImapConnector, ImapConnectorError, ImapCursor, secure_ssl_context
from backend.mail.parsing import (
    MAX_HEADER_BYTES,
    MAX_TRANSFER_BYTES,
    MailContentLimitError,
    decode_body_part,
    html_to_text,
    select_body_part,
    trim_quoted_reply,
)


HEADER = (
    b"Subject: =?utf-8?b?6Z2i6K+V6YCa55+l?=\r\n"
    b"From: recruiter@invalid\r\n"
    b"Date: Sat, 29 Aug 2026 02:00:00 +0000\r\n\r\n"
)


class FakeImapClient:
    def __init__(self, *, uidvalidity: int = 7, uidnext: int = 44) -> None:
        self.uidvalidity = uidvalidity
        self.uidnext = uidnext
        self.calls: list[tuple] = []
        self.search_result = [42, 43]
        self.structure = (
            (b"text", b"plain", (b"charset", b"utf-8"), None, None, b"quoted-printable", 100, 4),
            (
                b"text",
                b"html",
                (b"charset", b"utf-8"),
                None,
                None,
                b"7bit",
                200,
                5,
            ),
            b"alternative",
        )
        self.body = "面试时间：2026年9月2日 14:30".encode()
        self.header = HEADER
        self.missing_header_uids: set[int] = set()

    def login(self, username: str, authorization_code: str) -> None:
        self.calls.append(("login", username, authorization_code))

    def id_(self, values: dict[str, str]) -> None:
        self.calls.append(("id", values))

    def select_folder(self, folder: str, readonly: bool) -> dict[bytes, int]:
        self.calls.append(("select", folder, readonly))
        return {b"UIDVALIDITY": self.uidvalidity, b"UIDNEXT": self.uidnext}

    def search(self, criteria: list[object]) -> list[int]:
        self.calls.append(("search", criteria))
        return self.search_result

    def fetch(self, uids: list[int], items: list[str]) -> dict[int, dict[bytes, object]]:
        self.calls.append(("fetch", tuple(uids), tuple(items)))
        if "BODYSTRUCTURE" in items:
            return {uids[0]: {b"UID": uids[0], b"BODYSTRUCTURE": self.structure}}
        body_item = next((item for item in items if item.startswith("BODY.PEEK[") and "HEADER" not in item), None)
        if body_item:
            section = body_item.split("[", 1)[1].split("]", 1)[0]
            return {uids[0]: {b"UID": uids[0], f"BODY[{section}]<0>".encode(): self.body}}
        return {
            uid: {
                b"UID": uid,
                b"INTERNALDATE": datetime(2026, 8, 29, 2, tzinfo=timezone.utc),
                b"RFC822.SIZE": 1234,
                b"BODY[HEADER.FIELDS (SUBJECT FROM DATE)]<0>": self.header,
            }
            for uid in uids
            if uid not in self.missing_header_uids
        }

    def unselect_folder(self) -> None:
        self.calls.append(("unselect",))

    def logout(self) -> None:
        self.calls.append(("logout",))


class Factory:
    def __init__(self, client: FakeImapClient) -> None:
        self.client = client
        self.args: tuple | None = None

    def __call__(self, host: str, **kwargs: object) -> FakeImapClient:
        self.args = (host, kwargs)
        return self.client


def test_ssl_context_requires_verification_and_tls_12() -> None:
    context = secure_ssl_context()
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.minimum_version == ssl.TLSVersion.TLSv1_2


def test_qq_scan_uses_readonly_finite_uid_snapshot_and_peek() -> None:
    fake = FakeImapClient()
    factory = Factory(fake)
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=factory)

    with connector:
        result = connector.scan_headers(ImapCursor(uidvalidity=7, last_uid=41))

    assert factory.args is not None
    assert factory.args[0] == "imap.qq.com"
    assert factory.args[1]["port"] == 993
    assert factory.args[1]["ssl"] is True
    assert ("select", "INBOX", True) in fake.calls
    assert ("search", ["UID", "42:43"]) in fake.calls
    assert [message.uid for message in result.messages] == [42, 43]
    assert result.messages[0].header.subject == "面试通知"
    assert result.proposed_cursor == ImapCursor(uidvalidity=7, last_uid=43)
    fetch_call = next(call for call in fake.calls if call[0] == "fetch")
    header_query = next(item for item in fetch_call[2] if str(item).startswith("BODY.PEEK[HEADER.FIELDS"))
    assert "MESSAGE-ID" not in str(header_query)
    assert "MIME" not in str(header_query)
    assert str(header_query).endswith(f"<0.{MAX_HEADER_BYTES + 1}>")
    assert ("unselect",) in fake.calls
    assert ("logout",) in fake.calls
    assert all(call[0] not in {"store", "close"} for call in fake.calls)


def test_first_new_only_scan_sets_snapshot_without_searching() -> None:
    fake = FakeImapClient(uidnext=501)
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector:
        result = connector.scan_headers(None)

    assert result.messages == ()
    assert result.proposed_cursor.last_uid == 500
    assert not any(call[0] == "search" for call in fake.calls)


def test_uidvalidity_change_uses_24_hour_bounded_backfill() -> None:
    fake = FakeImapClient(uidvalidity=9, uidnext=44)
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    reference = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
    with connector:
        result = connector.scan_headers(ImapCursor(7, 400), now=reference)

    search = next(call for call in fake.calls if call[0] == "search")
    assert search[1] == ["SINCE", reference.date() - timedelta(days=1), "UID", "1:43"]
    assert result.cursor_reset is True
    assert result.uidvalidity == 9


def test_uidvalidity_change_uses_caller_overlap_from_last_success() -> None:
    fake = FakeImapClient(uidvalidity=9, uidnext=44)
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    overlap = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    with connector:
        connector.scan_headers(ImapCursor(7, 400), reset_since=overlap)

    search = next(call for call in fake.calls if call[0] == "search")
    assert search[1] == ["SINCE", overlap.date(), "UID", "1:43"]


def test_163_sends_truthful_id_after_login_before_examine() -> None:
    fake = FakeImapClient()
    connector = ImapConnector("163", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector:
        connector.scan_headers(None)

    names = [call[0] for call in fake.calls]
    assert names.index("login") < names.index("id") < names.index("select")
    identity = next(call[1] for call in fake.calls if call[0] == "id")
    assert identity == {"name": "CareerApplicationAssistant", "version": "0.1.0"}


def test_fetch_body_chooses_plain_non_attachment_part_with_peek() -> None:
    fake = FakeImapClient()
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector:
        body = connector.fetch_body(42)

    assert body is not None
    assert body.content_type == "text/plain"
    assert "2026年9月2日" in body.text
    body_fetch = [call for call in fake.calls if call[0] == "fetch"][-1]
    assert body_fetch[2] == ("UID", "BODY.PEEK[1]<0.1048577>")


def test_attachment_text_part_is_not_downloaded() -> None:
    fake = FakeImapClient()
    fake.structure = (
        b"text",
        b"plain",
        (b"charset", b"utf-8", b"name", b"resume.txt"),
        None,
        None,
        b"7bit",
        100,
        4,
        None,
        (b"attachment", (b"filename", b"resume.txt")),
    )
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector:
        body = connector.fetch_body(42)

    assert body is None
    assert len([call for call in fake.calls if call[0] == "fetch"]) == 1


def test_attached_multipart_is_not_traversed() -> None:
    leaf = (b"text", b"plain", (b"charset", b"utf-8"), None, None, b"7bit", 50, 2)
    attached_multipart = (
        leaf,
        b"mixed",
        (b"boundary", b"synthetic"),
        (b"attachment", (b"filename", b"forwarded.eml")),
    )
    assert select_body_part(attached_multipart) is None


def test_bodystructure_size_limit_prevents_body_fetch() -> None:
    fake = FakeImapClient()
    fake.structure = (b"text", b"plain", (b"charset", b"utf-8"), None, None, b"7bit", 1024 * 1024 + 1, 4)
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector, pytest.raises(ImapConnectorError, match="mail_body_transfer_too_large"):
        connector.fetch_body(42)
    assert len([call for call in fake.calls if call[0] == "fetch"]) == 1


def test_partial_fetch_rejects_server_payload_above_body_cap() -> None:
    fake = FakeImapClient()
    fake.body = b"x" * (MAX_TRANSFER_BYTES + 1)
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector, pytest.raises(ImapConnectorError, match="mail_body_transfer_too_large"):
        connector.fetch_body(42)
    body_fetch = [call for call in fake.calls if call[0] == "fetch"][-1]
    assert body_fetch[2] == ("UID", f"BODY.PEEK[1]<0.{MAX_TRANSFER_BYTES + 1}>")


def test_partial_header_fetch_skips_payload_above_header_cap() -> None:
    fake = FakeImapClient()
    fake.header = b"x" * (MAX_HEADER_BYTES + 1)
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector:
        result = connector.scan_headers(ImapCursor(uidvalidity=7, last_uid=41))
    assert result.messages == ()
    assert [item.reason for item in result.skipped] == [
        "mail_header_too_large",
        "mail_header_too_large",
    ]


def test_partial_header_response_skips_missing_uid_and_advances_finite_snapshot() -> None:
    fake = FakeImapClient()
    fake.missing_header_uids.add(43)
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector:
        result = connector.scan_headers(ImapCursor(uidvalidity=7, last_uid=41))

    assert [message.uid for message in result.messages] == [42]
    assert [(item.uid, item.reason) for item in result.skipped] == [
        (43, "mail_header_missing")
    ]
    assert result.proposed_cursor == ImapCursor(uidvalidity=7, last_uid=43)


def test_body_parser_uses_gb18030_and_html_never_exposes_script_or_url() -> None:
    original = "面试通知".encode("gb18030")
    decoded = decode_body_part(original, content_type="text/plain", charset="x-invalid", transfer_encoding="8bit")
    assert decoded.text == "面试通知"
    assert decoded.charset == "gb18030"
    assert decoded.used_fallback is True

    rendered = html_to_text(
        '<div>面试安排</div><script src="https://tracker.example.invalid/a">secret()</script>'
        '<img src="https://pixel.example.invalid/x"><form>hidden</form>'
    )
    assert rendered == "面试安排"
    assert "https://" not in rendered


def test_mime_depth_and_quote_trimming_are_conservative() -> None:
    structure: object = (b"text", b"plain", None, None, None, b"7bit", 10, 1)
    for _ in range(11):
        structure = (structure, b"mixed")
    with pytest.raises(MailContentLimitError, match="mail_mime_too_deep"):
        select_body_part(structure)

    trimmed = trim_quoted_reply("新的面试时间是明天\n\n-----Original Message-----\n旧的拒绝通知")
    assert trimmed.text == "新的面试时间是明天"
    assert trimmed.trimmed is True
    untouched = trim_quoted_reply("候选人提到 Original Message 这个术语，但不是引用头。")
    assert untouched.trimmed is False

    quote_only_html = trim_quoted_reply(
        html_to_text("<blockquote><p>第一轮面试时间：2026年9月3日</p></blockquote>")
    )
    assert quote_only_html.quoted_only is True


def test_pre_set_cancellation_is_reported_as_cancelled() -> None:
    fake = FakeImapClient()
    cancelled = Event()
    cancelled.set()
    connector = ImapConnector("qq", "person@invalid", "synthetic-code", client_factory=Factory(fake))
    with connector, pytest.raises(ImapConnectorError, match="^imap_operation_cancelled$"):
        connector.scan_headers(
            ImapCursor(uidvalidity=7, last_uid=41),
            cancel_event=cancelled,
        )
    assert not any(call[0] == "search" for call in fake.calls)


def test_scan_headers_chunks_large_backfill_without_skipping_remaining_uids() -> None:
    fake = FakeImapClient(uidnext=5002)
    fake.search_result = list(range(1, 5002))
    connector = ImapConnector(
        "qq",
        "person@invalid",
        "synthetic-code",
        client_factory=Factory(fake),
    )
    with connector:
        result = connector.scan_headers(None, since=date(2026, 8, 1))
        fake.search_result = [5001]
        second = connector.scan_headers(result.proposed_cursor)
    assert len(result.messages) == 5000
    assert result.snapshot_uid == 5000
    assert result.proposed_cursor.last_uid == 5000
    assert [message.uid for message in second.messages] == [5001]
    assert second.proposed_cursor.last_uid == 5001
    searches = [call for call in fake.calls if call[0] == "search"]
    assert searches[-1][1] == ["UID", "5001:5001"]
    assert all(
        len(call[1]) <= 100
        for call in fake.calls
        if call[0] == "fetch"
    )
