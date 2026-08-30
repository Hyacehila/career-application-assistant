"""Bounded MIME parsing used by the read-only mail connectors.

The functions in this module never resolve URLs or open files.  They operate only
on byte strings already fetched from a mailbox and deliberately reject oversized
or deeply nested content.
"""

from __future__ import annotations

import base64
import binascii
import quopri
import re
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesHeaderParser
from html.parser import HTMLParser
from typing import Any, Iterable

MAX_HEADER_BYTES = 64 * 1024
MAX_TRANSFER_BYTES = 1024 * 1024
MAX_DECODED_TEXT_BYTES = 512 * 1024
MAX_MIME_DEPTH = 10
MAX_MIME_PARTS = 50


class MailContentError(ValueError):
    """Safe, non-sensitive error raised for malformed mailbox content."""


class MailContentLimitError(MailContentError):
    """Mailbox content exceeded a configured in-memory processing limit."""


@dataclass(frozen=True, slots=True)
class ParsedHeader:
    subject: str
    sender: str
    message_id: str | None
    sent_at: datetime | None


@dataclass(frozen=True, slots=True)
class BodyPart:
    section: str
    content_type: str
    charset: str | None
    transfer_encoding: str
    size: int | None


@dataclass(frozen=True, slots=True)
class DecodedText:
    text: str
    charset: str
    used_fallback: bool


@dataclass(frozen=True, slots=True)
class QuoteTrimResult:
    text: str
    trimmed: bool
    quoted_only: bool = False


def parse_header_block(raw: bytes) -> ParsedHeader:
    """Parse only the explicitly fetched RFC 5322 header block."""

    if len(raw) > MAX_HEADER_BYTES:
        raise MailContentLimitError("mail_header_too_large")
    try:
        message = BytesHeaderParser(policy=policy.default).parsebytes(raw)
    except Exception as exc:  # email parsers can surface many malformed-input errors
        raise MailContentError("mail_header_invalid") from exc

    subject = _bounded_header(message.get("subject"), 998)
    sender = _bounded_header(message.get("from"), 998)
    message_id = _bounded_header(message.get("message-id"), 998) or None
    sent_at: datetime | None = None
    date_header = message.get("date")
    if date_header is not None:
        try:
            sent_at = date_header.datetime
        except (AttributeError, TypeError, ValueError, OverflowError):
            sent_at = None
    return ParsedHeader(subject, sender, message_id, sent_at)


def _bounded_header(value: Any, limit: int) -> str:
    if value is None:
        return ""
    rendered = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+", " ", str(value))
    return re.sub(r"\s+", " ", rendered).strip()[:limit]


def select_body_part(structure: Any) -> BodyPart | None:
    """Choose a non-attachment text body from an IMAP BODYSTRUCTURE value.

    ``text/plain`` wins globally over ``text/html``.  Attachments, nested
    messages, calendar parts and inline parts carrying a filename are ignored.
    """

    candidates: list[BodyPart] = []
    counter = [0]
    _collect_body_parts(structure, "", 0, counter, candidates)
    if not candidates:
        return None
    candidates.sort(key=lambda part: (part.content_type != "text/plain", part.section))
    return candidates[0]


def _collect_body_parts(
    node: Any,
    prefix: str,
    depth: int,
    counter: list[int],
    output: list[BodyPart],
) -> None:
    if depth > MAX_MIME_DEPTH:
        raise MailContentLimitError("mail_mime_too_deep")
    if not isinstance(node, (tuple, list)) or not node:
        return

    # Multipart BODYSTRUCTURE starts with one tuple per child, followed by subtype.
    if isinstance(node[0], (tuple, list)):
        child_index = 0
        while child_index < len(node) and isinstance(node[child_index], (tuple, list)):
            child_index += 1
        # For multipart nodes, subtype follows the child list, then optional
        # parameters/disposition.  Do not descend into an attached multipart.
        extensions = node[child_index + 1 :]
        multipart_params = _pairs_to_dict(extensions[0]) if extensions else {}
        multipart_disposition = ""
        multipart_disposition_params: dict[str, str] = {}
        for extension in extensions[1:]:
            if not isinstance(extension, (tuple, list)) or not extension:
                continue
            first = _body_text(extension[0]).lower()
            if first in {"attachment", "inline"}:
                multipart_disposition = first
                if len(extension) > 1:
                    multipart_disposition_params = _pairs_to_dict(extension[1])
                break
        if multipart_disposition == "attachment":
            return
        if multipart_params.get("name") or multipart_disposition_params.get("filename"):
            return

        for index, item in enumerate(node[:child_index], start=1):
            section = f"{prefix}.{index}" if prefix else str(index)
            _collect_body_parts(item, section, depth + 1, counter, output)
        return

    counter[0] += 1
    if counter[0] > MAX_MIME_PARTS:
        raise MailContentLimitError("mail_mime_too_many_parts")
    if len(node) < 7:
        return

    media_type = _body_text(node[0]).lower()
    subtype = _body_text(node[1]).lower()
    content_type = f"{media_type}/{subtype}"
    if content_type not in {"text/plain", "text/html"}:
        return

    params = _pairs_to_dict(node[2])
    disposition_name = ""
    disposition_params: dict[str, str] = {}
    for extension in node[8:]:
        if not isinstance(extension, (tuple, list)) or not extension:
            continue
        first = _body_text(extension[0]).lower()
        if first in {"attachment", "inline"}:
            disposition_name = first
            if len(extension) > 1:
                disposition_params = _pairs_to_dict(extension[1])
            break
    if disposition_name == "attachment":
        return
    if params.get("name") or disposition_params.get("filename"):
        return

    output.append(
        BodyPart(
            section=prefix or "1",
            content_type=content_type,
            charset=params.get("charset"),
            transfer_encoding=_body_text(node[5]).lower() or "7bit",
            size=_body_size(node[6]),
        )
    )


def _body_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="ignore")
    return "" if value is None else str(value)


def _body_size(value: Any) -> int | None:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size >= 0 else None


def _pairs_to_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, (tuple, list)):
        return {}
    result: dict[str, str] = {}
    iterator = iter(value)
    for key in iterator:
        try:
            item = next(iterator)
        except StopIteration:
            break
        normalized = _body_text(key).lower()
        if normalized:
            result[normalized] = _body_text(item)
    return result


def decode_body_part(
    raw: bytes,
    *,
    content_type: str,
    charset: str | None,
    transfer_encoding: str,
) -> DecodedText:
    """Decode one selected text part using bounded UTF-8/GB18030 fallbacks."""

    if len(raw) > MAX_TRANSFER_BYTES:
        raise MailContentLimitError("mail_body_transfer_too_large")
    decoded_bytes = _decode_transfer(raw, transfer_encoding)
    if len(decoded_bytes) > MAX_DECODED_TEXT_BYTES:
        raise MailContentLimitError("mail_body_decoded_too_large")

    declared = (charset or "").strip().strip('"').lower()
    encodings = _unique(item for item in (declared, "utf-8", "gb18030") if item)
    text: str | None = None
    used = ""
    used_fallback = False
    for index, encoding in enumerate(encodings):
        try:
            text = decoded_bytes.decode(encoding, errors="strict")
            used = encoding
            used_fallback = index > 0
            break
        except (LookupError, UnicodeDecodeError):
            continue
    if text is None:
        text = decoded_bytes.decode("utf-8", errors="replace")
        used = "utf-8"
        used_fallback = True

    text = text.replace("\x00", "")
    if content_type.lower() == "text/html":
        text = html_to_text(text)
    text = _limit_text(text)
    return DecodedText(text=text, charset=used, used_fallback=used_fallback)


def _decode_transfer(raw: bytes, encoding: str) -> bytes:
    normalized = (encoding or "").strip().lower()
    try:
        if normalized == "base64":
            return base64.b64decode(re.sub(rb"\s+", b"", raw), validate=False)
        if normalized == "quoted-printable":
            return quopri.decodestring(raw)
    except (binascii.Error, ValueError) as exc:
        raise MailContentError("mail_body_transfer_invalid") from exc
    if normalized in {"", "7bit", "8bit", "binary"}:
        return raw
    # Unknown encodings are kept byte-for-byte; charset decoding remains bounded.
    return raw


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _limit_text(text: str) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) > MAX_DECODED_TEXT_BYTES:
        raise MailContentLimitError("mail_body_text_too_large")
    return text


_DROP_HTML_TAGS = {"script", "style", "noscript", "svg", "template", "form"}
_BLOCK_HTML_TAGS = {
    "address",
    "article",
    "br",
    "div",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "li",
    "p",
    "section",
    "table",
    "td",
    "th",
    "tr",
}


class _SafeHTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in _DROP_HTML_TAGS:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and (
            normalized == "blockquote"
            or any(
                name.lower() == "class"
                and value
                and any(token in {"gmail_quote", "gmail_extra"} for token in value.split())
                for name, value in attrs
            )
        ):
            self.parts.append("\n-----Original Message-----\n")
        elif self._ignored_depth == 0 and normalized in _BLOCK_HTML_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in _DROP_HTML_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and normalized in _BLOCK_HTML_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Convert HTML to text without resolving any URL or external resource."""

    _limit_text(html)
    try:
        from bs4 import BeautifulSoup  # imported lazily for lightweight test setups
    except ImportError:
        parser = _SafeHTMLTextParser()
        parser.feed(html)
        parser.close()
        rendered = "".join(parser.parts)
    else:
        soup = BeautifulSoup(html, "html.parser")
        for node in soup.find_all(tuple(_DROP_HTML_TAGS)):
            node.decompose()
        for node in soup.find_all("blockquote"):
            node.insert_before("\n-----Original Message-----\n")
        for node in soup.select(".gmail_quote, .gmail_extra"):
            node.insert_before("\n-----Original Message-----\n")
        rendered = soup.get_text("\n")
    rendered = re.sub(r"[ \t\f\v]+", " ", rendered)
    rendered = re.sub(r"\n(?:\s*\n){2,}", "\n\n", rendered).strip()
    return _limit_text(rendered)


_EXACT_QUOTE_MARKERS = (
    re.compile(r"^\s*-{2,}\s*original message\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*forwarded message\s*-{2,}\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*原始邮件\s*-{2,}\s*$"),
    re.compile(r"^\s*-{2,}\s*转发邮件\s*-{2,}\s*$"),
)
_QUOTE_HEADER = re.compile(
    r"^\s*(from|sent|to|subject|date|发件人|发送时间|收件人|主题|日期)\s*[:：]",
    re.I,
)


def trim_quoted_reply(text: str) -> QuoteTrimResult:
    """Remove only high-confidence quoted tails; preserve uncertain content."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    cut_at: int | None = None
    has_prior_content = False
    for index, line in enumerate(lines):
        if not has_prior_content:
            if not line.strip():
                continue
            if any(pattern.match(line) for pattern in _EXACT_QUOTE_MARKERS):
                return QuoteTrimResult(normalized.strip(), False, True)
            if _QUOTE_HEADER.match(line):
                labels = {
                    match.group(1).lower()
                    for candidate in lines[index : index + 7]
                    if (match := _QUOTE_HEADER.match(candidate))
                }
                if len(labels) >= 3:
                    return QuoteTrimResult(normalized.strip(), False, True)
            if line.lstrip().startswith(">"):
                quoted_run = sum(
                    1 for candidate in lines[index : index + 5]
                    if candidate.lstrip().startswith(">")
                )
                if quoted_run >= 3:
                    return QuoteTrimResult(normalized.strip(), False, True)
            has_prior_content = bool(line.strip())
            continue
        if any(pattern.match(line) for pattern in _EXACT_QUOTE_MARKERS):
            cut_at = index
            break
        if _QUOTE_HEADER.match(line):
            labels = set()
            for candidate in lines[index : index + 7]:
                match = _QUOTE_HEADER.match(candidate)
                if match:
                    labels.add(match.group(1).lower())
            if len(labels) >= 3:
                cut_at = index
                break
        if line.lstrip().startswith(">"):
            quoted_run = 0
            for candidate in lines[index : index + 5]:
                if candidate.lstrip().startswith(">"):
                    quoted_run += 1
            if quoted_run >= 3:
                cut_at = index
                break
        has_prior_content = has_prior_content or bool(line.strip())
    if cut_at is None:
        return QuoteTrimResult(normalized.strip(), False, False)
    trimmed = "\n".join(lines[:cut_at]).strip()
    if not trimmed:
        return QuoteTrimResult(normalized.strip(), False, False)
    return QuoteTrimResult(trimmed, True, False)
