# 求职投递助手 / Career Application Assistant

This directory contains the public FastAPI, SQLite, React, and test implementation. Personal materials and application records stay outside it. Standard mode always uses `private/applications.sqlite`.

## Runtime entry points

- `server.py` starts standard mode on `127.0.0.1:8000`. It validates the fixed private overlay, initializes or migrates its database, enables the Agent and mail APIs, and serves `frontend/dist` when built.
- `demo_server.py` starts synthetic demo mode on `127.0.0.1:8001`. It uses a validated system-temporary session directory, seeds six fictional records, and omits both Agent and mail routes.
- `backend/` contains explicit standard, test, and demo application factories, migrations, the data store, API routers, and the read-only mail runtime.
- `frontend/` contains the Vite, React, and TypeScript interface. A single production build is shared by standard and demo modes.
- `tests/` contains backend and browser-loop tests. Test databases and fixtures must use validated temporary locations and must not open the standard database.

## Local commands

From the repository root:

```powershell
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --locked --extra dev
pnpm --dir app\frontend install --frozen-lockfile
pnpm --dir app\frontend build
```

Run standard mode after initializing the private overlay:

```powershell
pwsh -NoProfile -File .\scripts\Initialize-PrivateOverlay.ps1
.\.local\venv\Scripts\python.exe app\server.py
```

Run the isolated synthetic demo:

```powershell
pwsh -NoProfile -File .\scripts\Start-Demo.ps1
```

The loopback-only API rejects non-JSON writes and unexpected host/origin values. Standard startup and the typed Agent wrapper validate the health response identity and reject demo mode. Demo mode does not construct the mail service and does not expose `/api/mail/*` or `/api/agent/*`.

For setup, API details, verification, and troubleshooting, see [Development and API reference](../docs/development.md). Mail implementation and data boundaries are documented in [Mail ingestion](../docs/mail-ingestion.md) and [Security and privacy](../docs/security-and-privacy.md).
