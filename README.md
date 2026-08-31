# Career Application Assistant

English | [简体中文](README.zh-CN.md)

Career Application Assistant is a local, single-user workflow for discovering relevant roles, preparing a job application up to the final-submit boundary, reviewing it yourself, and then tracking progress as a structured event timeline.

It brings four practical pieces together:

1. Preference-driven job discovery: Codex explores relevant filters and detailed job descriptions within company career URLs you supply, then compares them with local evidence.
2. Guarded form preparation: Codex uses only the explicitly maintained local material file, fills the recruitment page already open in Chrome, and stops before final submission.
3. A useful local record: the board and table views keep job metadata, next actions, and validated stage events in one loopback-only application.
4. Optional read-only mail intake: Outlook, QQ Mail, and 163 Mail can produce bounded structured review candidates without turning the project into an inbox client.

> [!IMPORTANT]
> `private/` is Git-ignored local storage, not an encrypted vault. Protect the workspace, review backups and sync settings, and run the public-release check before publishing changes.

## The boundary

This project is not an auto-apply or bulk-application system. It never performs the final submit, confirm, send, or apply action. It also does not automate login, CAPTCHA, identity verification, payment, background-check consent, account creation, or external authorization. The user reviews the prepared form and personally submits it.

The supported flow is deliberately simple:

```text
local job preferences and application materials
        -> Codex inspects relevant filters and detailed job descriptions
        -> user selects a role
        -> Codex prepares the open recruitment form
        -> user reviews and personally submits
        -> structured events update the local timeline
        -> board and table views support follow-up
```

Form filling, application records, and mail ingestion all retain the same rule: raw candidate material and raw mail content do not become public repository data.

## Interface preview

The screenshots below come from the isolated synthetic demo. Every company, role, date, and timeline event is fictional; no personal application data is included.

![Synthetic application board showing compact cards](docs/assets/screenshots/demo-board.png)

Board cards show only the company and role. Select a card to open its full details, or drag it between columns when the application stage changes.

![Synthetic assessment record detail](docs/assets/screenshots/demo-assessment-detail.png)

The assessment detail shows the current stage, deadline, event timeline, and next action. Updating a tracked status records progress only; it never replaces the user's final review and submission on the recruitment site.

## Try the synthetic demo

The demo uses six clearly fictional records in an isolated system-temporary directory. It does not initialize `private/`, mount Agent or mail routes, or use mailbox credentials. All demo changes disappear with the session.

```powershell
pwsh -NoProfile -File .\scripts\Test-Environment.ps1 -Mode Demo
pwsh -NoProfile -File .\scripts\Start-Demo.ps1
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001). Use the in-page reset action, or run:

```powershell
pwsh -NoProfile -File .\scripts\Start-Demo.ps1 -Reset
```

Once the demo is running:

1. Browse the board and select any card to inspect its details.
2. Filter by `笔试 / 测评`, then open the fictional Qinghe record to review its assessment timeline.
3. Use the in-page reset action to restore the sample records, or press Ctrl+C to stop the server and clean the session directory.

The demo server is foreground-only.

## Run with your local workspace

Requirements: Windows, PowerShell 5.1 or later, Python 3.12 or later, [`uv`](https://docs.astral.sh/uv/), and [`pnpm`](https://pnpm.io/). The examples use `pwsh` from PowerShell 7; with Windows PowerShell 5.1, use `powershell.exe` instead.

```powershell
pwsh -NoProfile -File .\scripts\Initialize-PrivateOverlay.ps1
uv venv .local\venv --python 3.12
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.local\venv"
uv sync --locked --extra dev
pnpm --dir app\frontend install --frozen-lockfile
pnpm --dir app\frontend build
pwsh -NoProfile -File .\scripts\Test-Environment.ps1 -Mode Standard
.\.local\venv\Scripts\python.exe app\server.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The standard service accepts only the fixed `private/applications.sqlite` data file and listens only on loopback.

The initializer is safe to repeat: it creates missing `private/resume_materials.md` and `private/job_search_preferences.md` files from their public placeholder templates, without reading or replacing either existing file. Complete setup and validation are covered in [Getting started](docs/getting-started.md).

## Features

- A repository-scoped `$job-discovery` skill that uses private search preferences to select relevant career-site filters, traverses their accessible result pages without a fixed job quota, reads plausible job descriptions in depth, and produces an evidence-backed shortlist without saving or applying.
- Five-column board and detailed table with search, filters, sorting, pagination, responsive layout, details, next actions, and soft deletion.
- Ten precise statuses represented as append-only, validated timeline events; `applied` always requires explicit user confirmation.
- Typed Agent endpoints and a PowerShell wrapper for recording prepared forms and later status updates without direct SQLite access.
- Optional read-only incremental intake for Outlook through Microsoft Graph and QQ/163 through TLS IMAP, with a structured human-review queue.
- A synthetic, resettable demo that cannot access the production database, Agent routes, or mail runtime.
- Backend, frontend, browser-loop, release-policy, and Windows CI checks that do not require live recruitment or mailbox accounts.

## Safety summary

- Candidate materials and application data stay in ignored local paths; application code, rules, tests, and placeholders remain public.
- The standard API binds to `127.0.0.1:8000`; the demo binds to `127.0.0.1:8001`. Neither mode is a supported remote or multi-user deployment.
- Mail intake is read-only. Credentials and tokens use Windows Credential Manager or DPAPI-backed storage and fail closed if secure storage is unavailable.
- SQLite stores job metadata and bounded structured events, not resume contents, form answers, raw mail, attachments, verification codes, or meeting links.
- Public changes must be staged by exact path and checked with `scripts/Test-PublicRelease.ps1 -Staged`; a failing safety check must not be bypassed.

Read [Security and privacy](docs/security-and-privacy.md) before using personal data or enabling mail ingestion.

## Documentation

- [Documentation index](docs/README.md)
- [Getting started](docs/getting-started.md)
- [Application workflow](docs/application-workflow.md)
- [Mail ingestion](docs/mail-ingestion.md)
- [Security and privacy](docs/security-and-privacy.md)
- [Development and API reference](docs/development.md)
- [Backend layout](app/README.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Contributing and roadmap

Start with [CONTRIBUTING.md](CONTRIBUTING.md), review the [security policy](SECURITY.md), and check the [roadmap](ROADMAP.md). The project intentionally prioritizes local safety and an explicit human final-submit boundary over broader automation.

## License

Released under the [MIT License](LICENSE). Changes not yet released are recorded in [CHANGELOG.md](CHANGELOG.md).
