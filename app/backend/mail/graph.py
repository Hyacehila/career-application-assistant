"""Read-only Microsoft Graph mail delta client.

The client intentionally implements only the two GET operations needed by the
local ingestion service: Inbox message delta and ``uniqueBody`` retrieval.  It
does not expose a generic Graph request method, which keeps write operations
out of reach of this module.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit

from .credentials import (
    SecureStorageUnavailable,
    create_dpapi_token_cache,
    default_msal_cache_path,
)


GRAPH_ORIGIN = "https://graph.microsoft.com"
GRAPH_V1_PATH_PREFIX = "/v1.0/"
GRAPH_INBOX_DELTA_URL = f"{GRAPH_ORIGIN}/v1.0/me/mailFolders/inbox/messages/delta"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ("Mail.Read",)
REDIRECT_URI = "http://localhost"

MAX_DELTA_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_BODY_RESPONSE_BYTES = 1024 * 1024
MAX_DECODED_BODY_BYTES = 512 * 1024
MAX_DELTA_PAGES = 200
MAX_DELTA_MESSAGES = 5000


class GraphError(RuntimeError):
    """Base class for errors that contain no token, URL, or message content."""


class GraphAuthenticationRequired(GraphError):
    """The account needs an interactive sign-in."""


class GraphCursorExpired(GraphError):
    """The saved Graph delta cursor is no longer usable."""


class GraphMessageUnavailable(GraphError):
    """A message disappeared after the delta page was read."""


class GraphThrottled(GraphError):
    """Graph requested that polling pause for ``retry_after`` seconds."""

    def __init__(self, retry_after: float | None) -> None:
        super().__init__("Microsoft Graph throttled the request.")
        self.retry_after = retry_after


class GraphTransientError(GraphError):
    """A retryable Graph service error."""


class GraphProtocolError(GraphError):
    """Graph returned an invalid or unsafe response."""


class GraphPayloadTooLarge(GraphProtocolError):
    """A response exceeded a configured in-memory safety limit."""


@dataclass(frozen=True, slots=True)
class GraphMailHeader:
    """Transient header data used by the recruitment-message gate."""

    message_id: str
    internet_message_id: str | None
    subject: str
    sender_name: str
    sender_address: str
    received_at: datetime


@dataclass(frozen=True, slots=True)
class GraphMailBody:
    """A transient plain-text Graph ``uniqueBody`` value."""

    message_id: str
    text: str


@dataclass(frozen=True, slots=True)
class GraphDeltaResult:
    """A full-page delta batch and its commit-ready continuation cursor.

    ``delta_link`` is the final ``@odata.deltaLink`` for ordinary batches.  A
    bounded large backfill may instead return a validated ``@odata.nextLink``;
    callers persist it identically and resume on the next poll.
    """

    messages: tuple[GraphMailHeader, ...]
    delta_link: str


def _load_msal() -> ModuleType:
    try:
        return importlib.import_module("msal")
    except (ImportError, OSError):
        raise SecureStorageUnavailable("Microsoft authentication support is unavailable.") from None


class OutlookAuth:
    """MSAL public-client authentication backed exclusively by DPAPI."""

    def __init__(
        self,
        client_id: str,
        *,
        cache_path: str | Path | None = None,
        application: Any | None = None,
        msal_module: ModuleType | Any | None = None,
        extensions_module: ModuleType | Any | None = None,
        platform: str | None = None,
    ) -> None:
        self.client_id = _validate_client_id(client_id)
        self._cache_path = Path(cache_path) if cache_path is not None else None
        if application is not None:
            self._application = application
            return

        if self._cache_path is None:
            self._cache_path = default_msal_cache_path()
        token_cache = create_dpapi_token_cache(
            self._cache_path,
            extensions_module=extensions_module,
            platform=platform,
        )
        module = msal_module or _load_msal()
        public_client_type = getattr(module, "PublicClientApplication", None)
        if public_client_type is None:
            raise SecureStorageUnavailable("MSAL public-client support is unavailable.")
        try:
            self._application = public_client_type(
                client_id=self.client_id,
                authority=AUTHORITY,
                token_cache=token_cache,
            )
        except Exception:
            raise SecureStorageUnavailable("Could not initialize Microsoft authentication.") from None

    @property
    def cache_path(self) -> Path | None:
        """Encrypted cache location, or ``None`` for an injected test application."""

        return self._cache_path

    def account_username(self) -> str | None:
        """Return the sole cached account name for transient masked display."""

        try:
            accounts = list(self._application.get_accounts())
        except Exception:
            return None
        if len(accounts) != 1:
            return None
        username = accounts[0].get("username")
        if not isinstance(username, str):
            return None
        value = username.strip()
        return value or None

    def acquire_interactive(self, *, timeout: int = 300) -> str:
        """Run MSAL's authorization-code + PKCE desktop login."""

        try:
            result = self._application.acquire_token_interactive(
                scopes=list(SCOPES),
                redirect_uri=REDIRECT_URI,
                timeout=timeout,
            )
        except Exception:
            raise GraphAuthenticationRequired("Interactive sign-in did not complete.") from None
        return _access_token_from_result(result)

    def acquire_silent(self, *, home_account_id: str | None = None) -> str:
        """Get a cached/refreshed access token without selecting the wrong user."""

        try:
            accounts = list(self._application.get_accounts())
        except Exception:
            raise GraphAuthenticationRequired("The Microsoft account must be reconnected.") from None

        if home_account_id is not None:
            accounts = [
                account
                for account in accounts
                if str(account.get("home_account_id") or "") == home_account_id
            ]
        if len(accounts) != 1:
            raise GraphAuthenticationRequired("The Microsoft account must be reconnected.")

        try:
            result = self._application.acquire_token_silent_with_error(
                scopes=list(SCOPES),
                account=accounts[0],
            )
        except Exception:
            raise GraphAuthenticationRequired("The Microsoft account must be reconnected.") from None
        return _access_token_from_result(result)


class GraphMailClient:
    """Small, GET-only client for Inbox incremental ingestion."""

    def __init__(
        self,
        access_token_provider: Callable[[], str],
        *,
        http_client: Any | None = None,
    ) -> None:
        self._access_token_provider = access_token_provider
        self._owns_http_client = http_client is None
        self._http = http_client if http_client is not None else self._create_http_client()

    @staticmethod
    def _create_http_client() -> Any:
        try:
            httpx = importlib.import_module("httpx")
        except (ImportError, OSError):
            raise GraphError("HTTP client support is unavailable.") from None
        return httpx.Client(timeout=30.0, follow_redirects=False)

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()

    def __enter__(self) -> GraphMailClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_delta(
        self,
        *,
        delta_link: str | None = None,
        since: datetime | None = None,
    ) -> GraphDeltaResult:
        """Download a complete Inbox delta round.

        The returned ``delta_link`` is commit-ready only after the caller has
        durably processed all returned messages.  A supplied link is treated as
        opaque and never combined with additional query parameters.
        """

        if delta_link is not None and since is not None:
            raise ValueError("delta_link and since are mutually exclusive")
        if delta_link is not None:
            url = _validate_delta_url(delta_link)
            params: Mapping[str, str] | None = None
        else:
            url = GRAPH_INBOX_DELTA_URL
            params_dict = {
                "changeType": "created",
                "$select": "id,subject,from,receivedDateTime",
            }
            if since is not None:
                params_dict["$filter"] = f"receivedDateTime ge {_graph_datetime(since)}"
            params = params_dict

        messages: list[GraphMailHeader] = []
        seen_urls: set[str] = set()
        for page_number in range(MAX_DELTA_PAGES):
            if url in seen_urls:
                raise GraphProtocolError("Microsoft Graph returned a paging loop.")
            seen_urls.add(url)

            page = self._get_json(
                url,
                params=params,
                prefer='IdType="ImmutableId", odata.maxpagesize=50',
                max_bytes=MAX_DELTA_RESPONSE_BYTES,
            )
            params = None
            values = page.get("value")
            if not isinstance(values, list):
                raise GraphProtocolError("Microsoft Graph returned an invalid delta page.")
            page_messages: list[GraphMailHeader] = []
            for value in values:
                if not isinstance(value, Mapping):
                    raise GraphProtocolError("Microsoft Graph returned an invalid message entry.")
                if "@removed" in value:
                    continue
                page_messages.append(_parse_header(value))
                if len(page_messages) > MAX_DELTA_MESSAGES:
                    # Never partially consume one malformed/oversized page: no
                    # continuation cursor identifies the unconsumed tail.
                    raise GraphPayloadTooLarge("Microsoft Graph delta page exceeded the message limit.")
            messages.extend(page_messages)

            next_link = page.get("@odata.nextLink")
            final_link = page.get("@odata.deltaLink")
            if next_link is not None and final_link is not None:
                raise GraphProtocolError("Microsoft Graph returned conflicting cursor links.")
            if next_link is not None:
                if not isinstance(next_link, str):
                    raise GraphProtocolError("Microsoft Graph returned an invalid paging link.")
                safe_next_link = _validate_delta_url(next_link)
                if (
                    len(messages) >= MAX_DELTA_MESSAGES
                    or page_number + 1 >= MAX_DELTA_PAGES
                ):
                    return GraphDeltaResult(
                        messages=tuple(messages),
                        delta_link=safe_next_link,
                    )
                url = safe_next_link
                continue
            if not isinstance(final_link, str):
                raise GraphProtocolError("Microsoft Graph did not return a delta cursor.")
            return GraphDeltaResult(
                messages=tuple(messages),
                delta_link=_validate_delta_url(final_link),
            )
        # The page-limit branch above returns before this can be reached.  Keep
        # a fail-closed guard in case the loop structure changes later.
        raise GraphPayloadTooLarge("Microsoft Graph delta exceeded the page limit.")

    def fetch_unique_body(self, message_id: str) -> GraphMailBody:
        """Fetch only the plain-text ``uniqueBody`` for one gated message."""

        safe_id = _validate_message_id(message_id)
        url = f"{GRAPH_ORIGIN}/v1.0/me/messages/{quote(safe_id, safe='')}"
        payload = self._get_json(
            url,
            params={"$select": "id,uniqueBody"},
            prefer='IdType="ImmutableId", outlook.body-content-type="text"',
            max_bytes=MAX_BODY_RESPONSE_BYTES,
        )
        unique_body = payload.get("uniqueBody")
        if not isinstance(unique_body, Mapping):
            raise GraphProtocolError("Microsoft Graph did not return a message body.")
        content_type = unique_body.get("contentType")
        content = unique_body.get("content")
        if not isinstance(content_type, str) or content_type.casefold() != "text":
            raise GraphProtocolError("Microsoft Graph did not return plain text.")
        if not isinstance(content, str):
            raise GraphProtocolError("Microsoft Graph returned invalid body content.")
        if len(content.encode("utf-8")) > MAX_DECODED_BODY_BYTES:
            raise GraphPayloadTooLarge("Microsoft Graph message body exceeded the text limit.")
        return GraphMailBody(message_id=safe_id, text=content)

    def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None,
        prefer: str,
        max_bytes: int,
    ) -> Mapping[str, Any]:
        safe_url = _validate_graph_url(url)
        token = self._access_token_provider()
        if not isinstance(token, str) or not token or any(char in token for char in "\r\n"):
            raise GraphAuthenticationRequired("The Microsoft account must be reconnected.")

        try:
            response = self._http.get(
                safe_url,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Prefer": prefer,
                },
            )
        except Exception:
            # Network exceptions may embed the opaque delta URL.  Suppress
            # exception chaining so an upstream traceback cannot disclose it.
            raise GraphTransientError("Microsoft Graph is temporarily unavailable.") from None

        status = int(getattr(response, "status_code", 0))
        if status == 401:
            raise GraphAuthenticationRequired("The Microsoft account must be reconnected.")
        if status == 410:
            raise GraphCursorExpired("The Microsoft Graph delta cursor expired.")
        if status == 404:
            raise GraphMessageUnavailable("The Microsoft Graph message is no longer available.")
        if status == 429:
            raise GraphThrottled(_retry_after_seconds(_header(response, "Retry-After")))
        if status in {408, 425} or 500 <= status <= 599:
            raise GraphTransientError("Microsoft Graph is temporarily unavailable.")
        if status < 200 or status >= 300:
            raise GraphError("Microsoft Graph rejected the read-only request.")

        declared_length = _header(response, "Content-Length")
        if declared_length is not None:
            try:
                if int(declared_length) > max_bytes:
                    raise GraphPayloadTooLarge("Microsoft Graph response exceeded the size limit.")
            except ValueError:
                pass
        content = getattr(response, "content", None)
        if isinstance(content, (bytes, bytearray)) and len(content) > max_bytes:
            raise GraphPayloadTooLarge("Microsoft Graph response exceeded the size limit.")
        try:
            payload = response.json()
        except Exception:
            raise GraphProtocolError("Microsoft Graph returned invalid JSON.") from None
        if not isinstance(payload, Mapping):
            raise GraphProtocolError("Microsoft Graph returned an invalid JSON object.")
        return payload


def _validate_client_id(client_id: str) -> str:
    value = client_id.strip()
    if not value or len(value) > 128 or any(char in value for char in "\r\n\x00"):
        raise ValueError("client_id is invalid")
    return value


def _validate_message_id(message_id: str) -> str:
    value = message_id.strip()
    if not value or len(value.encode("utf-8")) > 2048 or any(char in value for char in "\r\n\x00"):
        raise ValueError("message_id is invalid")
    return value


def _validate_graph_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise GraphProtocolError("Microsoft Graph returned an unsafe continuation link.") from exc
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != "graph.microsoft.com"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith(GRAPH_V1_PATH_PREFIX)
        or parsed.fragment
    ):
        raise GraphProtocolError("Microsoft Graph returned an unsafe continuation link.")
    return url


def _validate_delta_url(url: str) -> str:
    """Restrict opaque continuation links to this feature's Inbox delta shape."""

    safe_url = _validate_graph_url(url)
    parsed = urlsplit(safe_url)
    path = parsed.path
    segments = path.split("/")
    slash_shape = False
    if len(segments) == 7:
        slash_shape = (
            segments[0] == ""
            and [part.casefold() for part in segments[1:4]]
            == ["v1.0", "me", "mailfolders"]
            and [part.casefold() for part in segments[5:]] == ["messages", "delta"]
            and _safe_folder_identifier(segments[4])
        )

    # Graph's official delta examples normalize a well-known folder to the
    # OData key form: /me/mailfolders('AQMk...')/messages/delta.
    odata_prefix = "/v1.0/me/mailfolders('"
    odata_suffix = "')/messages/delta"
    folded_path = path.casefold()
    odata_shape = (
        folded_path.startswith(odata_prefix)
        and folded_path.endswith(odata_suffix)
        and _safe_folder_identifier(
            path[len(odata_prefix) : len(path) - len(odata_suffix)]
        )
    )
    query = parse_qsl(parsed.query, keep_blank_values=True)
    safe_token_query = (
        len(query) == 1
        and query[0][0].casefold() in {"$skiptoken", "$deltatoken"}
        and bool(query[0][1])
    )
    if not (slash_shape or odata_shape) or not safe_token_query:
        raise GraphProtocolError("Microsoft Graph returned an unsafe continuation link.")
    return safe_url


def _safe_folder_identifier(value: str) -> bool:
    folded = value.casefold()
    return bool(
        value
        and len(value) <= 2048
        and value not in {".", ".."}
        and not any(char in value for char in ("/", "\\", "'", "\x00"))
        and "%2f" not in folded
        and "%5c" not in folded
    )


def _graph_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("since must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_graph_datetime(value: Any) -> datetime:
    if not isinstance(value, str):
        raise GraphProtocolError("Microsoft Graph returned an invalid received time.")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise GraphProtocolError("Microsoft Graph returned an invalid received time.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GraphProtocolError("Microsoft Graph returned a time without a timezone.")
    return parsed


def _parse_header(value: Mapping[str, Any]) -> GraphMailHeader:
    message_id = value.get("id")
    if not isinstance(message_id, str):
        raise GraphProtocolError("Microsoft Graph returned a message without an id.")
    safe_id = _validate_message_id(message_id)

    internet_id = value.get("internetMessageId")
    if internet_id is not None and not isinstance(internet_id, str):
        raise GraphProtocolError("Microsoft Graph returned an invalid internet message id.")
    sender = value.get("from") or {}
    if not isinstance(sender, Mapping):
        raise GraphProtocolError("Microsoft Graph returned an invalid sender.")
    address = sender.get("emailAddress") or {}
    if not isinstance(address, Mapping):
        raise GraphProtocolError("Microsoft Graph returned an invalid sender address.")

    return GraphMailHeader(
        message_id=safe_id,
        internet_message_id=_bounded_text(internet_id or "", 2048) or None,
        subject=_bounded_text(value.get("subject") or "", 4096),
        sender_name=_bounded_text(address.get("name") or "", 1024),
        sender_address=_bounded_text(address.get("address") or "", 1024),
        received_at=_parse_graph_datetime(value.get("receivedDateTime")),
    )


def _bounded_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise GraphProtocolError("Microsoft Graph returned invalid header text.")
    clean = value.replace("\x00", "").strip()
    if len(clean.encode("utf-8")) > limit:
        raise GraphPayloadTooLarge("Microsoft Graph header text exceeded the size limit.")
    return clean


def _access_token_from_result(result: Any) -> str:
    if not isinstance(result, Mapping):
        raise GraphAuthenticationRequired("The Microsoft account must be reconnected.")
    token = result.get("access_token")
    if not isinstance(token, str) or not token or any(char in token for char in "\r\n"):
        raise GraphAuthenticationRequired("The Microsoft account must be reconnected.")
    return token


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", {})
    if not isinstance(headers, Mapping):
        return None
    value = headers.get(name)
    if value is None:
        value = headers.get(name.casefold())
    return str(value) if value is not None else None


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            target = parsedate_to_datetime(value)
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            return max(0.0, (target - datetime.now(UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


__all__ = [
    "GraphAuthenticationRequired",
    "GraphCursorExpired",
    "GraphDeltaResult",
    "GraphError",
    "GraphMailBody",
    "GraphMailClient",
    "GraphMailHeader",
    "GraphMessageUnavailable",
    "GraphPayloadTooLarge",
    "GraphProtocolError",
    "GraphThrottled",
    "GraphTransientError",
    "OutlookAuth",
]
