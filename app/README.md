# Public application board

This directory contains the public board code: a FastAPI service, a fixed
SQLite data layer, and the React/Vite/TypeScript frontend. Keep personal
materials and application records outside this directory; the database is
always created at `private/applications.sqlite`.

## Layout

- `server.py` — user entrypoint. Validates the `private/` overlay, initializes
  or migrates the fixed database, serves the API on `127.0.0.1:8000`, and serves
  the built frontend from `app/frontend/dist` when present.
- `backend/` — the FastAPI application factory, SQLite data layer, migrations,
  and the application/agent routers.
- `frontend/` — the Vite + React + TypeScript board UI (built to `frontend/dist`).
- `tests/` — backend pytest suite plus a public simulated recruitment fixture;
  all databases are injected under the system temp directory.

## Run locally

Requires `uv` and `pnpm` on PATH, plus a Python 3.12+ interpreter.

```powershell
# Backend: create the repo-local virtualenv and install pinned dependencies.
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --extra dev

# Frontend: install and build once.
pnpm --dir app\frontend install
pnpm --dir app\frontend build
```

Then start the service with a single command from the repository root:

```powershell
.\.local\venv\Scripts\python.exe app\server.py
```

Open `http://127.0.0.1:8000`. If the frontend is not built, the API still works
and `/` shows a short public hint page.

For the agent workflow, the service can be auto-started (idempotent) with:

```powershell
pwsh -NoProfile -File .\scripts\Start-BoardService.ps1
```

Agents use the typed wrapper below instead of assembling raw HTTP JSON. It
performs the health/start sequence and supports `FillCompleted` plus
`StatusUpdate`; status matching accepts an exact active `ApplicationId` before
falling back to URL or job metadata.

```powershell
pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action StatusUpdate -ApplicationId 42 `
  -Stage assessment -EventDate 2026-08-29 `
  -DeadlineDate 2026-09-01 -EventSource email_extract
```

The persistent browser regression uses a simulated recruitment form, a fake
in-memory upload, the typed Agent wrapper, and an isolated temporary SQLite:

```powershell
pnpm --dir app\frontend exec playwright install chromium
pwsh -NoProfile -File .\scripts\Test-AgentBrowserE2E.ps1
```

The service binds loopback only. Write requests must be JSON and come from a
loopback `Host`.

## Data and privacy

The only data file is `private/applications.sqlite`. It stores job metadata,
stage events, and the structured timeline — never candidate names, phone
numbers, addresses, form answers, attachment content, or raw email bodies.
`AGENTS.md` is the authority for how the agent records applications and updates
status; automation always stops before final submission.
