from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from backend.mail.graph import (
    GraphAuthenticationRequired,
    GraphCursorExpired,
    GraphMailClient,
    GraphMessageUnavailable,
    GraphPayloadTooLarge,
    GraphProtocolError,
    GraphThrottled,
    GraphTransientError,
    OutlookAuth,
)


def _mailbox(local: str, domain: str = "example.invalid") -> str:
    return f"{local}@{domain}"


class FakeResponse:
    def __init__(self, status_code: int, payload: object, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = json.dumps(payload).encode()
        self.headers = headers or {}

    def json(self) -> object:
        return self._payload


class FakeHttp:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def _message(message_id: str = "immutable-1") -> dict:
    return {
        "id": message_id,
        "subject": "Interview invitation",
        "from": {
            "emailAddress": {
                "name": "Example Recruiting",
                "address": _mailbox("recruiting"),
            }
        },
        "receivedDateTime": "2026-08-29T10:11:12Z",
    }


def test_outlook_auth_uses_common_public_client_dpapi_and_mail_read(tmp_path) -> None:
    created: dict[str, object] = {}

    class Persistence:
        is_available = True

        def __init__(self, location: str) -> None:
            self.location = location

    class Cache:
        def __init__(self, persistence: object) -> None:
            self.persistence = persistence

    class PublicClient:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

        def acquire_token_interactive(self, **kwargs: object) -> dict:
            created["interactive"] = kwargs
            return {"access_token": "synthetic-access-token"}

        def get_accounts(self) -> list[dict]:
            return [
                {
                    "home_account_id": "home-1",
                    "username": _mailbox("masked-source"),
                }
            ]

        def acquire_token_silent_with_error(self, **kwargs: object) -> dict:
            created["silent"] = kwargs
            return {"access_token": "synthetic-refreshed-token"}

    auth = OutlookAuth(
        "00000000-0000-0000-0000-000000000000",
        cache_path=tmp_path / "cache.bin",
        msal_module=SimpleNamespace(PublicClientApplication=PublicClient),
        extensions_module=SimpleNamespace(
            FilePersistenceWithDataProtection=Persistence,
            PersistedTokenCache=Cache,
        ),
        platform="win32",
    )

    assert created["authority"] == "https://login.microsoftonline.com/common"
    assert isinstance(created["token_cache"], Cache)
    assert auth.cache_path == tmp_path / "cache.bin"
    assert auth.account_username() == _mailbox("masked-source")
    assert auth.acquire_interactive() == "synthetic-access-token"
    assert created["interactive"] == {
        "scopes": ["Mail.Read"],
        "redirect_uri": "http://localhost",
        "timeout": 300,
    }
    assert "offline_access" not in created["interactive"]["scopes"]
    assert auth.acquire_silent(home_account_id="home-1") == "synthetic-refreshed-token"
    assert created["silent"]["scopes"] == ["Mail.Read"]


def test_silent_auth_refuses_ambiguous_or_failed_account() -> None:
    ambiguous = SimpleNamespace(
        get_accounts=lambda: [{"home_account_id": "one"}, {"home_account_id": "two"}]
    )
    auth = OutlookAuth("client-id", application=ambiguous)
    assert auth.cache_path is None
    assert auth.account_username() is None
    with pytest.raises(GraphAuthenticationRequired):
        auth.acquire_silent()

    failed = SimpleNamespace(
        get_accounts=lambda: [{"home_account_id": "one"}],
        acquire_token_silent_with_error=lambda **_: {
            "error": "interaction_required",
            "error_description": "must not be echoed",
        },
    )
    auth = OutlookAuth("client-id", application=failed)
    with pytest.raises(GraphAuthenticationRequired) as raised:
        auth.acquire_silent()
    assert "must not be echoed" not in str(raised.value)


def test_delta_reads_headers_only_follows_safe_links_and_returns_final_cursor() -> None:
    next_link = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$skiptoken=opaque"
    delta_link = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=opaque"
    http = FakeHttp(
        FakeResponse(
            200,
            {
                "value": [_message(), {"id": "deleted", "@removed": {"reason": "deleted"}}],
                "@odata.nextLink": next_link,
            },
        ),
        FakeResponse(200, {"value": [_message("immutable-2")], "@odata.deltaLink": delta_link}),
    )
    client = GraphMailClient(lambda: "synthetic-token", http_client=http)

    result = client.fetch_delta(since=datetime(2026, 8, 1, tzinfo=UTC))

    assert [message.message_id for message in result.messages] == ["immutable-1", "immutable-2"]
    assert result.messages[0].sender_address == _mailbox("recruiting")
    assert result.delta_link == delta_link
    assert http.calls[0]["params"] == {
        "changeType": "created",
        "$select": "id,subject,from,receivedDateTime",
        "$filter": "receivedDateTime ge 2026-08-01T00:00:00Z",
    }
    assert "body" not in http.calls[0]["params"]["$select"]
    assert "internetMessageId" not in http.calls[0]["params"]["$select"]
    assert http.calls[1]["params"] is None
    assert http.calls[1]["url"] == next_link
    assert all(call["headers"]["Authorization"] == "Bearer synthetic-token" for call in http.calls)
    assert all("ImmutableId" in call["headers"]["Prefer"] for call in http.calls)


def test_delta_accepts_cursor_without_adding_initial_parameters() -> None:
    cursor = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=a"
    http = FakeHttp(FakeResponse(200, {"value": [], "@odata.deltaLink": cursor}))
    result = GraphMailClient(lambda: "token", http_client=http).fetch_delta(delta_link=cursor)
    assert result.delta_link == cursor
    assert http.calls[0]["params"] is None


def test_large_delta_returns_page_boundary_continuation_cursor(monkeypatch) -> None:
    monkeypatch.setattr("backend.mail.graph.MAX_DELTA_MESSAGES", 1)
    next_link = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
        "$skiptoken=second-page"
    )
    final_link = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
        "$deltatoken=complete"
    )
    http = FakeHttp(
        FakeResponse(200, {"value": [_message("first")], "@odata.nextLink": next_link}),
        FakeResponse(200, {"value": [_message("second")], "@odata.deltaLink": final_link}),
    )
    client = GraphMailClient(lambda: "token", http_client=http)

    first_batch = client.fetch_delta()
    assert [message.message_id for message in first_batch.messages] == ["first"]
    assert first_batch.delta_link == next_link
    assert len(http.calls) == 1

    second_batch = client.fetch_delta(delta_link=first_batch.delta_link)
    assert [message.message_id for message in second_batch.messages] == ["second"]
    assert second_batch.delta_link == final_link
    assert len(http.calls) == 2


def test_single_delta_page_over_message_limit_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr("backend.mail.graph.MAX_DELTA_MESSAGES", 1)
    http = FakeHttp(
        FakeResponse(
            200,
            {
                "value": [_message("first"), _message("second")],
                "@odata.deltaLink": (
                    "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
                    "$deltatoken=complete"
                ),
            },
        )
    )

    with pytest.raises(GraphPayloadTooLarge):
        GraphMailClient(lambda: "token", http_client=http).fetch_delta()


def test_delta_page_cap_returns_safe_continuation_cursor(monkeypatch) -> None:
    monkeypatch.setattr("backend.mail.graph.MAX_DELTA_PAGES", 1)
    next_link = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
        "$skiptoken=resume-after-cap"
    )
    http = FakeHttp(FakeResponse(200, {"value": [], "@odata.nextLink": next_link}))

    result = GraphMailClient(lambda: "token", http_client=http).fetch_delta()

    assert result.messages == ()
    assert result.delta_link == next_link


@pytest.mark.parametrize(
    "unsafe_link",
    [
        "http://graph.microsoft.com/v1.0/me/messages/delta",
        "https://evil.invalid/v1.0/me/messages/delta",
        "https://graph.microsoft.com.evil.invalid/v1.0/me/messages/delta",
        "https://graph.microsoft.com/beta/me/messages/delta",
        "https://user:password" + "@graph.microsoft.com/v1.0/me/messages/delta",
        "https://graph.microsoft.com/v1.0/me/messages/delta?$skiptoken=x",
        "https://graph.microsoft.com/v1.0/users/other/mailFolders/inbox/messages/delta?$skiptoken=x",
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$skiptoken=x",
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta/extra?$skiptoken=x",
        "https://graph.microsoft.com/v1.0/me/mailFolders/..%2Fmessages/messages/delta?$skiptoken=x",
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$select=body",
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$skiptoken=",
    ],
)
def test_delta_rejects_unsafe_continuation_links(unsafe_link: str) -> None:
    http = FakeHttp(FakeResponse(200, {"value": [], "@odata.nextLink": unsafe_link}))
    with pytest.raises(GraphProtocolError):
        GraphMailClient(lambda: "token", http_client=http).fetch_delta()
    assert len(http.calls) == 1


def test_delta_accepts_official_odata_folder_id_continuation_shape() -> None:
    next_link = (
        "https://graph.microsoft.com/v1.0/me/mailfolders('AQMkFixtureFolderId')/"
        "messages/delta?$skiptoken=opaque"
    )
    final_link = (
        "https://graph.microsoft.com/v1.0/me/mailfolders('AQMkFixtureFolderId')/"
        "messages/delta?$deltatoken=complete"
    )
    http = FakeHttp(
        FakeResponse(200, {"value": [], "@odata.nextLink": next_link}),
        FakeResponse(200, {"value": [], "@odata.deltaLink": final_link}),
    )

    result = GraphMailClient(lambda: "token", http_client=http).fetch_delta()

    assert result.delta_link == final_link
    assert http.calls[1]["url"] == next_link


def test_graph_maps_expired_cursor_and_retry_after_without_response_body() -> None:
    cursor = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=a"
    expired = GraphMailClient(
        lambda: "token",
        http_client=FakeHttp(FakeResponse(410, {"error": {"message": "sensitive"}})),
    )
    with pytest.raises(GraphCursorExpired) as cursor_error:
        expired.fetch_delta(delta_link=cursor)
    assert "sensitive" not in str(cursor_error.value)

    throttled = GraphMailClient(
        lambda: "token",
        http_client=FakeHttp(FakeResponse(429, {}, {"Retry-After": "17"})),
    )
    with pytest.raises(GraphThrottled) as throttle_error:
        throttled.fetch_delta(delta_link=cursor)
    assert throttle_error.value.retry_after == 17


def test_graph_maps_message_404_to_nonfatal_message_error() -> None:
    client = GraphMailClient(
        lambda: "token",
        http_client=FakeHttp(FakeResponse(404, {"error": {"message": "must-not-echo"}})),
    )

    with pytest.raises(GraphMessageUnavailable) as raised:
        client.fetch_unique_body("immutable-message")

    assert "must-not-echo" not in str(raised.value)


def test_network_exception_does_not_chain_opaque_delta_url() -> None:
    class RaisingHttp:
        def get(self, url: str, **_: object) -> FakeResponse:
            raise RuntimeError(f"failed URL {url}")

    cursor = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?"
        "$deltatoken=do-not-log"
    )
    with pytest.raises(GraphTransientError) as raised:
        GraphMailClient(lambda: "token", http_client=RaisingHttp()).fetch_delta(
            delta_link=cursor
        )
    assert raised.value.__cause__ is None
    assert "do-not-log" not in str(raised.value)


def test_unique_body_is_get_only_plain_text_and_id_is_path_encoded() -> None:
    http = FakeHttp(
        FakeResponse(
            200,
            {"id": "id/with+characters", "uniqueBody": {"contentType": "text", "content": "Hello"}},
        )
    )
    body = GraphMailClient(lambda: "token", http_client=http).fetch_unique_body(
        "id/with+characters"
    )
    assert body.text == "Hello"
    assert http.calls[0]["url"].endswith("/id%2Fwith%2Bcharacters")
    assert http.calls[0]["params"] == {"$select": "id,uniqueBody"}
    assert 'body-content-type="text"' in http.calls[0]["headers"]["Prefer"]
    assert not hasattr(http, "post")
    assert not hasattr(http, "patch")


def test_unique_body_rejects_html_and_oversized_text(monkeypatch) -> None:
    html = FakeHttp(
        FakeResponse(200, {"uniqueBody": {"contentType": "html", "content": "<b>x</b>"}})
    )
    with pytest.raises(GraphProtocolError):
        GraphMailClient(lambda: "token", http_client=html).fetch_unique_body("id")

    monkeypatch.setattr("backend.mail.graph.MAX_DECODED_BODY_BYTES", 4)
    oversized = FakeHttp(
        FakeResponse(200, {"uniqueBody": {"contentType": "text", "content": "12345"}})
    )
    with pytest.raises(GraphPayloadTooLarge):
        GraphMailClient(lambda: "token", http_client=oversized).fetch_unique_body("id")


def test_token_with_header_injection_is_rejected_before_network() -> None:
    http = FakeHttp()
    with pytest.raises(GraphAuthenticationRequired):
        GraphMailClient(lambda: "token\r\ninjected", http_client=http).fetch_delta()
    assert http.calls == []


def test_since_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError):
        GraphMailClient(lambda: "token", http_client=FakeHttp()).fetch_delta(
            since=datetime(2026, 8, 1)
        )
