# Development and API reference

English | [简体中文](development.zh-CN.md)

## Repository layout

- `app/server.py`: fixed standard entrypoint at `127.0.0.1:8000`.
- `app/demo_server.py`: fixed synthetic demo entrypoint at `127.0.0.1:8001`.
- `app/backend/`: FastAPI factories, schema, migrations, store, routers, and mail implementation.
- `app/frontend/`: React, TypeScript, Vite, Vitest, and Playwright configuration.
- `app/tests/`: backend tests and the public simulated recruitment fixture.
- `scripts/`: private-overlay initialization, diagnostics, service/Agent wrappers, browser-loop regression, and release checks.

The explicit factories keep runtime authority separate:

- `create_app()` is standard mode and accepts no alternate production database.
- `create_test_app(paths)` accepts caller-supplied paths for isolated tests, retains the mail API, and disables scheduling. Test harnesses are responsible for providing temporary paths.
- `create_demo_app(paths)` accepts only a validated system-temporary demo session, does not construct the mail service, and omits mail and Agent routes.

See [app/README.md](../app/README.md) for a concise runtime overview.

## Install and run

```powershell
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --locked --extra dev
pnpm --dir app\frontend install --frozen-lockfile
pnpm --dir app\frontend build
```

Standard and demo startup steps are in [Getting started](getting-started.md). Development Vite runs on `127.0.0.1:5173` and proxies `/api` to standard mode on port 8000.

## Health and modes

`GET /api/health` preserves database and schema health fields and identifies the process:

```json
{
  "status": "ok",
  "database": "available",
  "schema_version": 3,
  "service": "career-application-assistant",
  "mode": "standard",
  "synthetic_data": false,
  "mail_ingestion": true
}
```

Test mode reports `mode: "test"`. Demo reports `mode: "demo"`, `synthetic_data: true`, and `mail_ingestion: false`. Startup and Agent scripts check these identity fields and always refuse demo mode.

## API overview

All endpoints are JSON under `/api`. POST and PATCH requests require `Content-Type: application/json`. Unknown fields are rejected.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Service identity, mode, database, and migration health |
| `GET` | `/api/applications` | Paginated records, filters, and five-column counts |
| `POST` | `/api/applications` | Create a pending-review record |
| `GET` | `/api/applications/{id}` | Record details and event timeline |
| `PATCH` | `/api/applications/{id}` | Edit metadata, notes, and next action without directly changing status |
| `DELETE` | `/api/applications/{id}` | Soft-delete a record |
| `POST` | `/api/applications/{id}/events` | Append a validated event and update status transactionally |
| `PATCH` | `/api/applications/{id}/events/{event_id}` | Correct event details while retaining its ID |
| `POST` | `/api/agent/fill-completed` | Idempotently record a prepared form as pending review |
| `POST` | `/api/agent/status-update` | Uniquely match an active record and append a structured event |
| `GET` | `/api/mail/accounts` | Sanitized provider states and pending counts |
| `POST` | `/api/mail/accounts/{provider}/connect` | Start Outlook authorization or validate/store an IMAP authorization code |
| `POST` | `/api/mail/accounts/{provider}/sync` | Start one bounded incremental read |
| `POST` | `/api/mail/accounts/{provider}/pause` | Pause polling while retaining secure state |
| `POST` | `/api/mail/accounts/{provider}/resume` | Resume polling and request a sync |
| `DELETE` | `/api/mail/accounts/{provider}` | Remove cursor and secure credential/token state |
| `GET` | `/api/mail/operations/{id}` | Poll a sanitized connect/sync operation |
| `GET` | `/api/mail/candidates` | List structured review candidates without raw mail fields |
| `POST` | `/api/mail/candidates/{id}/confirm` | Validate and append a reviewed candidate event |
| `POST` | `/api/mail/candidates/{id}/dismiss` | Ignore and redact a candidate |
| `POST` | `/api/demo/reset` | Demo only: atomically restore the six synthetic records from an empty JSON body |

Agent matching priority is exact active record ID, normalized public job URL, company plus job code, then company plus role plus location. Missing or archived IDs return `404`, conflicts return `409`, and validation failures return `422`. Clients must not change request meaning to work around these responses.

Demo reset returns `{"ok": true, "records_seeded": 6}`. The Agent and mail routes return `404` in demo mode; the reset route returns `404` outside demo mode.

## Verification

Run backend tests only through the repository environment:

```powershell
.\.local\venv\Scripts\python.exe -m pytest app\tests -q
```

The startup tests copy the required public runtime into an isolated temporary repository, capture only the service PID they start, and never open the standard database or terminate arbitrary port listeners.

Run frontend tests and the production build:

```powershell
pnpm --dir app\frontend test
pnpm --dir app\frontend build
```

Run the browser closed-loop regression after installing the lockfile-compatible Chromium:

```powershell
pnpm --dir app\frontend exec playwright install chromium
pwsh -NoProfile -File .\scripts\Test-AgentBrowserE2E.ps1
```

The regression uses a synthetic recruitment form and temporary database to exercise prepare, fixture upload, draft save, stop-before-submit, and pending-review recording. Playwright trace, screenshot, and video output are disabled. It does not read the standard database or require a live recruitment site.

Run public policy checks and whitespace validation:

```powershell
pwsh -NoProfile -File .\scripts\Test-PublicRelease.ps1 -PolicySelfTest
git diff --check
```

Provider-free mail tests use deterministic Graph and IMAP doubles. An optional no-auth smoke check may establish TLS only to `imap.qq.com:993` and `imap.163.com:993`; it must never send credentials and is not part of the required unit suite.

## Windows CI

The single CI workflow uses Windows, Python 3.12, Node 22, pnpm 10, and the locked dependencies. It runs the public-release check, pytest, Vitest, and production build. CI has read-only repository contents permission, no secrets, no mailbox connection, and no recruitment-site access.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Import check fails | Confirm Python 3.12+, activate the repository environment, and run the locked sync. |
| Frontend dependency check fails | Use pnpm 10 and install from the lockfile. |
| Startup refuses an existing listener | Inspect and stop the unrelated process; wrappers intentionally do not terminate it. |
| Agent command refuses health | Verify service identity, standard mode, and schema; Agent commands never target demo. |
| Agent returns `409` | Resolve multiple matches, a status conflict, or a new event on an ended record with the user. |
| Agent returns `422` | Supply required identity or event dates without guessing. |
| Demo reset fails | Confirm port 8001 is a healthy demo and send an empty JSON object. |
| Release check fails | Stop publication, inspect the exact failure and staged diff, and do not bypass the rule. |

Behavioral boundaries are defined in [Application workflow](application-workflow.md), [Mail ingestion](mail-ingestion.md), and [Security and privacy](security-and-privacy.md).
