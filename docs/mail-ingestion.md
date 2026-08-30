# Mail ingestion

English | [简体中文](mail-ingestion.zh-CN.md)

Mail ingestion is an optional, read-only background capability in standard mode. It is not an inbox client. Demo mode does not construct the mail service or mount `/api/mail/*`.

## Supported providers

| Provider | Connection | Incremental cursor | Secret storage |
| --- | --- | --- | --- |
| Outlook / Outlook.com | Microsoft Graph delegated `Mail.Read`, public-client authorization code flow with PKCE | Inbox delta link | MSAL cache encrypted with Windows DPAPI under local application data |
| QQ Mail | TLS IMAP on port 993 with a separately generated authorization code | `UIDVALIDITY` and last processed UID | Windows Credential Manager |
| 163 Mail | TLS IMAP on port 993 with a client authorization password | `UIDVALIDITY` and last processed UID | Windows Credential Manager |

The implementation has no SMTP, send, reply, forward, delete, move, mark-read, attachment-download, or webhook feature. Provider credentials and tokens are not written to SQLite, configuration files, logs, or `private/`. If secure Windows storage is unavailable, connection fails instead of falling back to plaintext.

## Outlook setup

Register a Microsoft Entra public client application. Allow personal Microsoft accounts when Outlook.com support is needed, configure `http://localhost` as a mobile/desktop redirect URI, and add only delegated `Mail.Read`. Enter the public Client ID in the local interface; no client secret is used.

MSAL performs interactive authorization with PKCE and refreshes through its DPAPI-protected cache. Inbox changes are read through the Microsoft Graph [message delta API](https://learn.microsoft.com/graph/api/message-delta?view=graph-rest-1.0). The authentication implementation uses [MSAL Python](https://github.com/AzureAD/microsoft-authentication-library-for-python); licensing details are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

Login, account recovery, CAPTCHA, multi-factor prompts, and external authorization must be completed by the user. The application does not read or enter verification codes.

## QQ Mail and 163 Mail setup

Enable IMAP in the provider settings and generate a dedicated client authorization code or client password. Never enter the normal web-login password. See the [QQ Mail connector instructions](https://hiflow.tencent.com/docs/applications/qq-mail/) and [NetEase Mail help](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac2ed007f2b27412aae).

The service connects only with verified TLS on port 993, opens Inbox using read-only `EXAMINE`, and uses UID queries with `BODY.PEEK`. It has no mailbox mutation API.

## Incremental processing

The first connection defaults to new messages only; an explicit 30- or 90-day backfill may be selected. One in-process scheduler polls connected accounts at a bounded interval.

Each pass first reads limited header metadata. A size-limited, non-attachment text body is fetched into memory only when a high-recall recruitment gate matches. HTML is converted to plain text offline; scripts, remote resources, links, and instructions inside mail are never executed.

The cursor advances only in the same successful transaction as the structured results. A read, parse, or write failure leaves it unchanged. `UIDVALIDITY` changes and expired Graph delta links trigger a bounded overlap rebuild, never an unbounded mailbox scan.

## Extraction and automatic updates

Only assessments and exact first, second, third, or HR interview rounds can be appended automatically, and only when all of these are true:

- exactly one active application matches the established priority order;
- required event, scheduled, or deadline dates are explicit;
- the status transition is safe and consistent;
- confidence meets the service threshold.

Generic interviews, ambiguous or conflicting dates, missing or multiple matches, `applied`, offers, rejections, withdrawals, archived applications, ended-record restarts, and unsafe transitions stay in the human review queue. The `applied` status always requires a `user_confirmation` event after personal final submission.

Mail text is untrusted input. It cannot change local rules, database schema, safe-storage boundaries, or application commands.

## Structured review queue

While pending, a candidate is limited to company, role, proposed stage, event/scheduled/deadline dates, confidence, matched record ID, reason codes, provider/fingerprint, and minimal queue metadata. The API and frontend do not expose subject, sender, body, attachments, meeting links, verification codes, or private contacts.

Confirming a safe candidate appends its validated event. Dismissing, deduplicating, or expiring a candidate immediately clears readable structured fields while retaining only minimal audit and deduplication metadata. Unreviewed candidates expire after 90 days. Disconnecting removes the provider cursor and the corresponding secure credential or token cache.

## Operations and troubleshooting

The Mail ingestion view shows sanitized connection state, sync controls, and structured candidates. Pausing retains the secure connection and cursor; resuming requests another bounded sync; disconnecting removes them.

| Symptom | Check |
| --- | --- |
| Outlook requests authorization again | Verify public-client configuration, the `http://localhost` redirect, and delegated `Mail.Read`, then reconnect. |
| QQ/163 authentication fails | Confirm IMAP is enabled and use the generated authorization code, not the web password. |
| Secure storage fails | Run in a supported Windows interactive user session with Credential Manager and DPAPI available. |
| A candidate is not auto-applied | Review the reason code; ambiguity and unsafe transitions are deliberately routed to a person. |
| Sync repeats old mail | Check for a bounded cursor rebuild after `UIDVALIDITY` or delta invalidation; do not reset or scan the mailbox manually. |

The public API operations are listed in [Development and API reference](development.md), and persistence limits are explained in [Security and privacy](security-and-privacy.md).
