# Career Application Assistant

English | [简体中文](README.zh-CN.md)

A local, single-user job application workspace that combines guarded browser form filling, structured AI-assisted status updates, and a practical application board. The agent can prepare an application and maintain its timeline, but the user always reviews and performs the final submission.

> [!IMPORTANT]
> Private files are kept inside a Git-ignored `private/` overlay, not in an encrypted vault. Protect the local workspace, exclude it from unwanted backup or sync tools, and run the release check before publishing changes.

## What the project does

| Area | Included behavior |
| --- | --- |
| Form assistance | Codex reads only `private/resume_materials.md`, fills the recruitment page already open in Chrome, uploads explicitly declared attachments, and stops before final submission. |
| Agent tracking | After a form is prepared, the agent checks or starts the local API and creates an idempotent `pending_review` record. |
| Status updates | A user-confirmed submission, assessment notice, interview invitation, offer, rejection, or withdrawal is appended as a validated timeline event. |
| Mail ingestion | Outlook is polled through Microsoft Graph delta queries; QQ Mail and 163 Mail are polled through read-only IMAPS UID scans. Only structured recruitment events reach the board. |
| Local board | React board and table views provide search, filters, sorting, pagination, drag-based stage updates, detail drawers, next actions, and soft deletion. |
| Local data | FastAPI writes one SQLite database at `private/applications.sqlite`; no arbitrary production database path is accepted. |
| Guardrails | The API is loopback-only, rejects non-JSON writes and unexpected hosts, validates dates and stage transitions, and never lets a form-fill callback mark an application as submitted. |

The interface has ten precise statuses grouped into five board columns:

| Board column | Statuses |
| --- | --- |
| Pending review | `pending_review` |
| Applied | `applied` |
| Assessment | `assessment` |
| Interview | `interview_1`, `interview_2`, `interview_3`, `interview_hr` |
| Ended | `offer`, `rejected`, `withdrawn` |

## What it deliberately does not do

- It never clicks “Submit application”, “Confirm”, “Send”, or an equivalent final action.
- It is not an email client: there is no inbox UI, message search, attachment download, SMTP, reply, forwarding, deletion, or read/unread mutation.
- It does not expose a webhook. Microsoft Graph is polled because the supported service is local-only and has no public HTTPS callback.
- It does not automate login, CAPTCHA, identity verification, account creation, payment, background-check consent, or external authorization.
- It does not scrape jobs, recommend roles, send notifications, sync calendars, or run unattended bulk applications.
- It does not provide accounts, cloud sync, remote access, or a multi-user deployment.
- It does not store resume contents, candidate contact details, form answers, attachments, raw email bodies, verification codes, or meeting links in SQLite.

## How the pieces fit together

```text
private/resume_materials.md ──> Codex ──> open recruitment page
                                  │         (stops before final submit)
                                  │
                                  └──────> local JSON API ──> private/applications.sqlite
                                                    ▲
                                                    │
                            Graph / read-only IMAPS │
                                    mail providers ─┤
                                                    │
                                      React board/table/mail setup
```

`AGENTS.md` defines the agent’s browser, privacy, attachment, conflict, and database-writing rules. The browser UI and the agent share the same HTTP API; the agent must not execute SQL directly.

## Quick start

### Prerequisites

The documented and tested workflow uses Windows with:

- Git;
- PowerShell 5.1 or later (`pwsh` is used in the examples);
- Python 3.12 or later;
- [`uv`](https://docs.astral.sh/uv/);
- [`pnpm`](https://pnpm.io/).

### 1. Create the private overlay

Run this once in a clean clone:

```powershell
pwsh -NoProfile -File .\scripts\Initialize-PrivateOverlay.ps1
```

The initializer creates `private/resume_materials.md` from the public placeholder template. It refuses to overwrite a non-empty `private/` directory.

Complete the generated file, place only its declared attachments in `private/`, then validate the private workspace:

```powershell
pwsh -NoProfile -File .\scripts\Test-PrivateWorkspace.ps1 -WorkspaceRoot .\private -InitializeResumeHash
pwsh -NoProfile -File .\scripts\Test-PrivateWorkspace.ps1 -WorkspaceRoot .\private
```

The validator reports check names and pass/fail results without printing personal values. The hash records the expected resume attachment and remains ignored by Git.

### 2. Install dependencies and build the frontend

From the repository root:

```powershell
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --extra dev
pnpm --dir app\frontend install
pnpm --dir app\frontend build
```

Dependencies are resolved from `uv.lock` and `app/frontend/pnpm-lock.yaml`. Local environments, caches, and frontend build output are ignored.

### 3. Start the application

```powershell
.\.local\venv\Scripts\python.exe app\server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). This one process serves the API and the built frontend on loopback only. A missing database is initialized only at `private/applications.sqlite`; an unsupported schema version stops startup instead of overwriting data.

The idempotent startup entry point used by agents is:

```powershell
pwsh -NoProfile -File .\scripts\Start-BoardService.ps1
```

It checks `/api/health`, starts the service in a hidden local window when necessary, waits about ten seconds, and fails without installing, downloading, or deleting anything.

## Using the board

The default view is a five-column board. The same records can be viewed as a nine-column table. Both views share search and filters, and their state is represented in the URL.

- Create or edit a record from the interface. Company and role are required.
- Open a card or row to inspect its record ID, job metadata, current progress, event history, and next action.
- Change status through the status form or drag a card. Moving to Applied requires explicit confirmation that the user submitted it; assessments and interviews require the relevant dates.
- Correct event dates or details without replacing the event ID.
- Delete from the interface to archive a record; events are retained as history.

On screens narrower than 768 px, the board becomes a single-stage list and details open in a bottom drawer. The service still remains local-only; the responsive layout does not enable LAN access.

## Read-only mailbox ingestion

Open the **Mail ingestion** view to connect any combination of the three supported providers:

| Provider | Connection | Incremental cursor | Secret storage |
| --- | --- | --- | --- |
| Outlook / Outlook.com | Microsoft Graph delegated `Mail.Read`, authorization-code login with PKCE | Inbox delta link | MSAL cache encrypted by Windows DPAPI under `%LOCALAPPDATA%` |
| QQ Mail | TLS IMAP on port 993 with a separately generated authorization code | `UIDVALIDITY` plus last processed UID | Windows Credential Manager |
| 163 Mail | TLS IMAP on port 993 with a client authorization password | `UIDVALIDITY` plus last processed UID | Windows Credential Manager |

For Outlook, register a Microsoft Entra **public client** application, allow personal Microsoft accounts if needed, configure `http://localhost` as a mobile/desktop redirect URI, and add delegated `Mail.Read`. Enter only its public Client ID in the UI; no client secret is used. MSAL performs the interactive authorization-code flow with PKCE, requests offline access as part of its default client flow, and refreshes tokens from the encrypted cache. The implementation follows the official [message delta API](https://learn.microsoft.com/graph/api/message-delta?view=graph-rest-1.0) and uses the open-source [MSAL Python](https://github.com/AzureAD/microsoft-authentication-library-for-python) client.

For QQ or 163, enable IMAP in the provider settings and generate a dedicated client authorization code/password. Never enter the normal web-login password. See the [QQ Mail connector instructions](https://hiflow.tencent.com/docs/applications/qq-mail/) and [NetEase Mail help](https://help.mail.126.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac2ed007f2b27412aae).

The first connection defaults to “new messages only”; optional 30- or 90-day backfill is available. A single scheduler polls connected accounts about every five minutes. Header fields are read first, and a bounded non-attachment text body is fetched only when the subject/sender gate suggests a recruitment event. IMAP sessions select Inbox read-only and use UID fetches plus `BODY.PEEK`; the service has no mailbox mutation API.

Exact interview rounds and assessments may be written automatically only when one active application matches by the existing priority rules, required dates are explicit, the transition is safe, and confidence is at least 90. Generic interviews, ambiguous or conflicting dates, missing/multiple matches, `applied`, terminal stages, archived records, and unsafe transitions remain in the review queue. “Applied” still requires the user to confirm that they personally submitted the application.

Only company, role, proposed stage, dates, confidence, match ID, provider/fingerprint, and queue metadata are persisted while review is pending. Subject, sender, full body, attachments, meeting links, verification codes, and private contacts are never stored. Pending candidates expire and are structurally redacted after 90 days; confirmed, ignored, duplicate, and expired candidates are redacted immediately. Disconnecting deletes the provider cursor and secure credential/token cache.

## Using Codex as the database entry point

Start a Codex task in the repository root so that it loads `AGENTS.md`. For browser filling, connect the Codex Chrome extension, open the recruitment application page yourself, and use a direct request such as:

> Follow `AGENTS.md` to fill the currently open recruitment application. Stop before final submission and record the prepared application in the local board.

The expected closed loop is:

1. Codex fills high-confidence fields from `private/resume_materials.md` and replaces the current application’s resume attachment when required.
2. Before presenting the review summary, it uses `scripts/Invoke-BoardAgent.ps1 -Action FillCompleted`. The command performs the health check, invokes `Start-BoardService.ps1` when needed, and calls `POST /api/agent/fill-completed`.
3. The resulting status is `pending_review`, never `applied`; command output contains only the record ID, action, and current status.
4. You review the page and submit it yourself.
5. Only after an explicit statement such as “I have personally submitted this application” may Codex use the same command with the record ID to append an `applied` event sourced from `user_confirmation`.

The command accepts typed parameters rather than raw JSON, database paths, alternate hosts, or arbitrary endpoints. For example:

```powershell
pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action FillCompleted `
  -CompanyName 'Example Company' `
  -JobTitle 'Example Role' `
  -JobCode 'EXAMPLE-001' `
  -Location 'Shanghai' `
  -JobUrl 'https://jobs.example.test/example-001'

pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action StatusUpdate `
  -ApplicationId 42 `
  -Stage interview_1 `
  -EventDate 2026-08-29 `
  -ScheduledDate 2026-09-02 `
  -EventSource email_extract
```

For later tracking, provide the company/role context and the relevant notification. For example:

> I received the following assessment notice for this application. Extract only the stage and dates, update the matching board record, and do not save the original message.

Codex may write the update only when exactly one active record matches, the stage is unambiguous, and required dates are present. Status updates prefer a record ID returned earlier or shown by the board; metadata matching is used only when no trusted ID is available. Email-derived updates use `email_extract`. Interviews must map exactly to first, second, third, or HR interview. Missing dates, non-standard round names, multiple matches, ended-record conflicts, or API errors cause the agent to stop and ask rather than guess.

The local application stores only the structured result. The message is still processed in the Codex conversation, so remove unrelated private details before sharing it if they are not needed for matching.

## API overview

All API responses are JSON under `/api`. POST and PATCH requests must use `Content-Type: application/json`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Service, database, and migration health |
| `GET` | `/api/applications` | Paginated records, filter options, and five board counts |
| `POST` | `/api/applications` | Manually create a pending-review record |
| `GET` | `/api/applications/{id}` | Application details and event timeline |
| `PATCH` | `/api/applications/{id}` | Edit metadata, notes, and next action; cannot change status directly |
| `DELETE` | `/api/applications/{id}` | Soft-delete an application |
| `POST` | `/api/applications/{id}/events` | Append a validated status event and update current status transactionally |
| `PATCH` | `/api/applications/{id}/events/{event_id}` | Correct event scheduling details while retaining the event ID |
| `POST` | `/api/agent/fill-completed` | Idempotently record a completed form as pending review |
| `POST` | `/api/agent/status-update` | Uniquely match an active application and append a structured event |
| `GET` | `/api/mail/accounts` | Three provider connection states and pending counts |
| `POST` | `/api/mail/accounts/{provider}/connect` | Start Outlook authorization or validate/store an IMAP authorization code |
| `POST` | `/api/mail/accounts/{provider}/sync` | Start one incremental read |
| `POST` | `/api/mail/accounts/{provider}/pause` | Pause polling without deleting credentials |
| `POST` | `/api/mail/accounts/{provider}/resume` | Resume polling and request an immediate sync |
| `DELETE` | `/api/mail/accounts/{provider}` | Delete the cursor and secure credential/token cache |
| `GET` | `/api/mail/operations/{id}` | Poll a connect/sync operation using sanitized status codes |
| `GET` | `/api/mail/candidates` | List structured review candidates; raw mail fields are absent |
| `POST` | `/api/mail/candidates/{id}/confirm` | Validate and append a reviewed timeline event |
| `POST` | `/api/mail/candidates/{id}/dismiss` | Ignore and redact a pending candidate |

Agent status matching uses, in order: exact active record ID; normalized public job URL; company plus job code; or company plus role plus location. An archived or unknown ID returns `404`. Other match conflicts return `409`, while missing or invalid information returns `422`. The agent must not change request meaning to work around these responses.

## Data and privacy model

### Tracked public content

- application code and tests in `app/`;
- setup and safety scripts in `scripts/`;
- `AGENTS.md`, both READMEs, dependency locks, license, and the placeholder-only template.

### Ignored local content

- `private/resume_materials.md`;
- `private/applications.sqlite` and SQLite files generally;
- resume, photo, document, and image attachments;
- `.resume.sha256`, local environments, caches, editor state, and build output.

SQLite contains job metadata, the current status, structured event dates, a short note, next-action fields, mailbox cursors, and the bounded structured review queue. It contains neither mailbox addresses nor credentials, tokens, or raw messages. QQ/163 authorization codes use Windows Credential Manager targets keyed by an opaque account ID. Outlook uses `msal-extensions` with Windows DPAPI and fails closed rather than creating a plaintext cache. The API strips query parameters and fragments from public job URLs and rejects undeclared request fields.

For backup, stop the service before copying `private/applications.sqlite` to another protected local location. Do not put backups in Git. Git ignore rules do not prevent operating-system backup software or cloud-folder synchronization from copying `private/`; configure those systems separately.

Do not expose port 8000 through a reverse proxy, port forward, tunnel, or LAN binding. The application has no user authentication because its supported deployment is loopback-only.

## Publishing safely

Stage only the intended public paths—never `git add .`, `git add -A`, or `git add -f`—then run:

```powershell
git add -- README.md README.zh-CN.md
# Add every other reviewed public file by its exact path; do not stage a directory wholesale.
pwsh -NoProfile -File .\scripts\Test-PublicRelease.ps1 -Staged
git diff --cached --check
git diff --cached --name-only
git diff --cached
```

The release check enforces the public path allowlist and rejects private paths, databases, common attachment types, recognizable secrets, personal contact patterns, untracked files, and missing required policy sections. It is a guardrail, not a mathematical proof that prose contains no identifying information; review the full staged diff before committing and do not bypass a failed check.

## Development and verification

Run the backend suite with the repository environment:

```powershell
.\.local\venv\Scripts\python.exe -m pytest app\tests -q
```

Run frontend tests and a production build:

```powershell
pnpm --dir app\frontend test
pnpm --dir app\frontend build
```

Provider-free tests use deterministic Graph/IMAP doubles. A separate no-auth smoke check may open TLS connections to `imap.qq.com:993` and `imap.163.com:993`; it must never send credentials and is not required for the unit suite.

Install the lockfile-compatible Chromium once, then run the persistent browser closed-loop regression:

```powershell
pnpm --dir app\frontend exec playwright install chromium
pwsh -NoProfile -File .\scripts\Test-AgentBrowserE2E.ps1
```

The test creates an isolated SQLite database under the system temp directory and exercises “fill fields → upload a fixture attachment → save draft → stop before final submission → record pending review through the Agent command.” It closes the fixture service and deletes temporary data without reading the real `private/` database.

For frontend development, keep the API on port 8000 and run Vite in a second terminal:

```powershell
pnpm --dir app\frontend dev
```

Open `http://127.0.0.1:5173`; Vite proxies `/api` to the local FastAPI service.

Backend-specific layout and startup notes are available in [app/README.md](app/README.md).

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Startup says the private overlay is missing | Run `Initialize-PrivateOverlay.ps1` from the repository root. |
| Startup script cannot find Python | Create `.local/venv` and run `uv sync --extra dev`. |
| `/` shows a build hint instead of the board | Run `pnpm --dir app\frontend build`, then restart the service. |
| Health returns `503` | Check that `private/` is writable and that the database schema is supported; do not delete or replace the database automatically. |
| Agent receives `409` | More than one record matched, a stage conflicts, or an ended record received a new process event; resolve it with the user. |
| Agent receives `422` | Required job identity, interview date, assessment schedule/deadline, or another validated field is missing or invalid. |
| Outlook says reauthorization is required | Confirm the app is a public client, the redirect URI is `http://localhost`, delegated `Mail.Read` is enabled, and reconnect from the Mail ingestion view. |
| QQ/163 authentication fails | Enable IMAP, generate a dedicated authorization code/client password, and do not use the web-login password. |
| Credential store is unavailable | Run on Windows under an interactive user account with Credential Manager and DPAPI available; the service intentionally has no plaintext fallback. |
| Private workspace validation fails | Resolve placeholders, declared attachments, ordering, or resume-hash mismatch without printing the underlying values. |
| Public release check fails | Stop publication, inspect the named check, and correct the staged content instead of bypassing it. |

## License

Released under the [MIT License](LICENSE). Mail ingestion builds on maintained open-source libraries rather than embedding a third-party inbox; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
