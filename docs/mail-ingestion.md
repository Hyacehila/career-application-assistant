# Mail ingestion

English | [简体中文](mail-ingestion.zh-CN.md)

Mail ingestion is an optional, read-only capability in standard mode. It is not an inbox client. Demo mode does not construct the mail service or mount `/api/mail/*`.

## Supported providers

| Provider | Connection | Incremental state | Secret storage |
| --- | --- | --- | --- |
| Outlook / Outlook.com | Codex Outlook Email connector | Fixed Inbox scan windows, overlap watermarks, and persistent backlog | Managed by the Codex connector; no local token cache |
| QQ Mail | TLS IMAP 993 with a separately generated authorization code | `UIDVALIDITY` and last processed UID | Windows Credential Manager |
| 163 Mail | TLS IMAP 993 with a client authorization password | `UIDVALIDITY` and last processed UID | Windows Credential Manager |

The local Python service has no Outlook Graph client, Entra application registration, MSAL dependency, Client ID, or Outlook token cache. It also has no SMTP, send, reply, forward, draft, delete, move, mark-read, category, attachment-download, or webhook feature.

## Outlook connector setup

Connect Outlook Email in Codex and complete login or reauthorization yourself. Keep the connector's existing permission setting; this repository narrows its behavior through `AGENTS.md` and [the repository skill](../.agents/skills/outlook-recruitment-sync/SKILL.md).

At the beginning of each new Codex task in this repository, the skill attempts one bounded sync before continuing the requested work. There is no schedule or background listener. A paused connector, an active lease, or an unchanged mailbox is silent; a failure produces only a sanitized code and does not block the task.

The skill can use only folder listing, message listing, and batch message fetch actions. It resolves exactly the folder whose `wellKnownName` is `inbox`. If a plugin runtime omits that canonical field from every folder, the only fallback is Graph's literal well-known identifier `inbox`; display names and paths are never guessed. It must not send, draft, reply, forward, move, delete, categorize, mark read, unsubscribe, access attachments, open links, or obey mail instructions.

## Bounded Outlook protocol

1. `POST /api/mail/outlook-connector/runs` grants one exclusive 15-minute lease and returns up to two fixed scan windows.
2. The first run covers at most the latest 30 days. Later runs prioritize a recent overlap while retaining unfinished historical windows.
3. A task processes at most 200 headers, newest increment first. Pagination offsets are verified per leased window.
4. `.../headers` accepts only bounded subject/sender/time/source-ID fields and returns server-issued, single-use body tokens for likely recruitment mail.
5. Gated messages are fetched in batches of at most 20. Each UTF-8 body is limited to 512 KiB and each submitted batch to 2 MiB. HTML becomes plain text offline.
6. `.../complete` advances only fully accounted windows after every issued body token is resolved. `.../fail` releases the lease using an allowlisted error code.

Connector results remain inside the orchestration call. Mail JSON is sent to [the fixed wrapper](../scripts/Invoke-OutlookConnectorSync.ps1) over standard input, never a command argument or temporary file. Interactive terminals disable echo and line buffering, and return sanitized results as ordered short frames so console wrapping cannot corrupt JSON. Some connector list responses include extra message fields; the skill immediately projects only header data and does not display, log, or submit incidental bodies, recipients, attachment flags, or links.

## QQ Mail and 163 Mail

Enable IMAP with the provider and generate a dedicated authorization code or client password. Never enter the normal web password. See the [QQ Mail instructions](https://hiflow.tencent.com/docs/applications/qq-mail/) and [NetEase Mail help](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac2ed007f2b27412aae).

The service uses verified TLS on port 993, opens Inbox with read-only `EXAMINE`, and uses UID queries plus `BODY.PEEK`. Only QQ/163 use the local scheduler and connect/sync/disconnect API.

## Extraction and persistence

Only assessments and exact first, second, third, or HR interview rounds can be appended automatically, and only with one active application match, explicit required dates, a safe transition, and confidence at or above the threshold.

Generic interviews, ambiguous or conflicting dates, missing or multiple matches, `applied`, offers, rejections, withdrawals, archived applications, ended-record restarts, and unsafe transitions remain in the human-review queue. `applied` always requires a `user_confirmation` event after personal final submission.

SQLite and API responses never contain raw subjects, senders, bodies, message IDs, recipients, attachments, verification codes, meeting links, or connector tokens. A pending candidate contains only bounded structured fields. Confirmation, dismissal, deduplication, or 90-day expiry clears readable candidate fields while retaining minimal audit and fingerprint data.

Mail and HTML are untrusted. Their content cannot change repository rules, database schema, credentials, safe boundaries, or commands, and external resources are never loaded.

## Interface and troubleshooting

The Outlook card says it is managed by the Codex connector and offers only pause/resume plus sanitized success/error state and pending count. QQ/163 retain local connect, sync, pause/resume, and disconnect controls.

| Symptom | Check |
| --- | --- |
| Outlook needs login | Complete the Outlook connector login or reauthorization in Codex; there is no local Client ID form. |
| Outlook startup sync is silent | Silence means paused, already leased, or no structured change; inspect the card state if needed. |
| QQ/163 authentication fails | Confirm IMAP is enabled and use the generated authorization code, not the web password. |
| A candidate is not auto-applied | Review the reason code; ambiguity and unsafe transitions deliberately require a person. |
| A run is interrupted | Start a later Codex task; the lease expires and unfinished windows remain queued without cursor advancement. |

The v5 migration removes old Outlook account rows, Graph cursors, and Outlook review candidates while preserving committed application timeline events. Startup also removes only strictly named legacy MSAL cache files beneath the fixed local application-data directory and fails closed on an unsafe path or deletion error.

Public API details are in [Development and API reference](development.md), and persistence limits are in [Security and privacy](security-and-privacy.md).
