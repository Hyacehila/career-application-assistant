# Getting started

English | [简体中文](getting-started.zh-CN.md)

## Requirements

The supported workflow uses Windows with Git, PowerShell 5.1 or later, Python 3.12 or later, [`uv`](https://docs.astral.sh/uv/), and [`pnpm`](https://pnpm.io/). Commands below use `pwsh` from PowerShell 7; replace it with `powershell.exe` on Windows PowerShell 5.1. Standard and demo modes are loopback-only.

Run the fixed-name environment checks at any point:

```powershell
pwsh -NoProfile -File .\scripts\Test-Environment.ps1 -Mode Standard
pwsh -NoProfile -File .\scripts\Test-Environment.ps1 -Mode Demo
```

The check prints only named PASS/FAIL results. It does not print candidate data, credentials, attachment names, usernames, or absolute user paths.

## Install dependencies

From the repository root:

```powershell
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --locked --extra dev
pnpm --dir app\frontend install --frozen-lockfile
pnpm --dir app\frontend build
```

`uv.lock` and `app/frontend/pnpm-lock.yaml` provide the reproducible dependency inputs. The local environment, caches, and frontend build output are ignored by Git.

## Start the synthetic demo

The demo is the fastest way to inspect the product without a private overlay or mailbox account:

```powershell
pwsh -NoProfile -File .\scripts\Start-Demo.ps1
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001). The foreground process creates a validated session directory directly under the system temporary root and seeds six fictional records. Ctrl+C stops the process and removes only that session directory.

If an already healthy demo owns port 8001, a normal start returns successfully without creating another process. Reset it from the page or from another terminal:

```powershell
pwsh -NoProfile -File .\scripts\Start-Demo.ps1 -Reset
```

An unknown service on port 8001 is rejected. The demo never initializes `private/`, constructs the mail runtime, or exposes mail and Agent routes.

## Start standard mode

Initialize the private overlay:

```powershell
pwsh -NoProfile -File .\scripts\Initialize-PrivateOverlay.ps1
```

The command initializes `private/resume_materials.md` and `private/job_search_preferences.md` independently from their public example templates. An existing destination file is reported without being read or replaced, while a missing destination is created. Other files in `private/` are not enumerated, changed, or deleted.

Complete both generated files, using the preference file only for discovery scope and ranking, and add only the attachments declared in the material file. Validate the local workspace without exposing values:

```powershell
pwsh -NoProfile -File .\scripts\Test-PrivateWorkspace.ps1 -WorkspaceRoot .\private -InitializeResumeHash
pwsh -NoProfile -File .\scripts\Test-PrivateWorkspace.ps1 -WorkspaceRoot .\private
```

Start the service in the foreground:

```powershell
.\.local\venv\Scripts\python.exe app\server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Standard mode accepts only `private/applications.sqlite`. A missing database is created there; an unsupported schema version stops startup instead of overwriting data.

The idempotent background entry used by the Agent workflow is:

```powershell
pwsh -NoProfile -File .\scripts\Start-BoardService.ps1
```

It verifies the health service identity and standard mode, starts the fixed local service only when needed, and rejects demo or unknown services.

## Development frontend

Keep the standard API on port 8000, then run Vite separately:

```powershell
pnpm --dir app\frontend dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies `/api` to the standard loopback service.

## Common startup problems

| Symptom | Check |
| --- | --- |
| Private overlay check fails | Run the initializer, then fix missing placeholders or declarations without printing private values. |
| Local Python is missing | Create `.local/venv`, set `UV_PROJECT_ENVIRONMENT`, and run the locked sync. |
| `/` shows a build hint | Build the frontend, then restart the backend process. |
| Health returns `503` | Check write access and the supported schema; do not delete or replace the database automatically. |
| Port 8000 or 8001 is rejected | Stop the unrelated listener. The scripts do not terminate unknown processes. |
| Secure mail storage is unavailable | Use a supported interactive Windows session; the service does not fall back to plaintext. |

Continue with the [application workflow](application-workflow.md) or read [development and API details](development.md).
