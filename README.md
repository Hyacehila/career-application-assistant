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
- It does not read a mailbox automatically or connect to an email account. The user supplies the relevant message when requesting an update.
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
                                            React board/table
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

SQLite contains job metadata, the current status, structured event dates, a short note, and next-action fields. It is not a candidate profile store. The API strips query parameters and fragments from public job URLs and rejects undeclared request fields.

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
| Private workspace validation fails | Resolve placeholders, declared attachments, ordering, or resume-hash mismatch without printing the underlying values. |
| Public release check fails | Stop publication, inspect the named check, and correct the staged content instead of bypassing it. |

## License

Released under the [MIT License](LICENSE).
