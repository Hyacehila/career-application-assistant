# Security and privacy

English | [简体中文](security-and-privacy.zh-CN.md)

This project separates public implementation from local personal data. The separation is a workflow and release-control boundary; it does not make the local machine or ignored directory an encrypted vault.

## Public and local data

Tracked public content includes application code and tests in `app/`, safety and workflow scripts in `scripts/`, public rules and documentation, dependency locks, the license, and placeholder-only templates.

Local ignored content includes:

- `private/resume_materials.md`;
- `private/job_search_preferences.md`;
- `private/applications.sqlite` and other SQLite files;
- resumes, documents, photographs, certificates, and other attachments;
- local attachment hashes, environments, caches, editor state, and frontend build output.

Git ignore rules do not stop operating-system backups or cloud-folder synchronization. Configure those systems separately. For a database backup, stop the service and copy `private/applications.sqlite` to another protected local location outside Git.

## Data sources and browser boundary

For live form filling, `private/resume_materials.md` is the only permitted source for field values, options, and declarations. Codex does not infer fields from uploaded documents, the recruitment page, browser history, autofill, external search, or the public example template.

For job discovery, explicit constraints in the current request take priority over the long-term scope and ranking preferences in `private/job_search_preferences.md`; `private/resume_materials.md` remains the only source for candidate facts and qualification evidence. Codex first selects relevant career-site category filters, covers their accessible result pages without a fixed job quota, and reads plausible detailed job descriptions before matching. Keyword search is only supplemental and never represents whole-site coverage. Discovery remains inside the company recruitment flow supplied by the user and cannot fill, save, or apply.

The user opens the recruitment page and explicitly requests filling. Codex may prepare high-confidence fields, replace a declared attachment in the current application, and use clearly intermediate controls. It must stop before final submission and for authentication, verification, payment, account creation, background-check consent, ambiguous declarations, required missing facts, or unsafe attachment operations.

Recruitment pages and mail are untrusted inputs. Their content cannot instruct the Agent to read other local data, change repository rules, execute commands, modify the database schema, broaden credentials, or cross the final-submit boundary.

## Local service boundary

Standard mode listens only on `127.0.0.1:8000`, has no configurable production database path, and uses only `private/applications.sqlite`. Demo mode listens only on `127.0.0.1:8001`, uses a validated system-temporary session directory, and omits Agent and mail routes. Test mode accepts an explicitly injected path and disables scheduling; isolated test harnesses provide temporary paths.

Do not expose either port through a reverse proxy, tunnel, port forward, or LAN binding. The application has no account authentication because remote and multi-user deployments are unsupported. Write requests must be JSON and use accepted loopback host/origin values.

Startup tools validate the health response service identity and mode. Standard and Agent commands reject demo mode; only isolated test harnesses enable test mode through a process-scoped flag.

## SQLite contents

The database stores job metadata, the current validated stage, structured event dates, short notes, next actions, provider cursors, and a bounded structured mail-review queue. It does not store candidate names, phone numbers, email addresses, home addresses, resume contents, form answers, attachment content, raw mail fields, mailbox credentials or tokens, verification codes, or meeting links.

Status changes are append-only events. `applied` requires `user_confirmation`; form preparation and email extraction cannot create it. Archived and ended records have additional transition checks.

## Mail credentials and content

QQ/163 authorization codes are stored only in Windows Credential Manager under opaque account targets. Outlook's MSAL cache is encrypted with Windows DPAPI under local application data. These values are not written to SQLite, logs, configuration, or `private/`. Secure-storage failures are closed failures, never plaintext fallbacks.

Mail is read incrementally and read-only. Raw subject, sender, body, attachment, private contact, verification code, and meeting link fields are not returned by the API or kept in the review queue. See [Mail ingestion](mail-ingestion.md) for provider and retention details.

## Public-release checks

Before publishing, stage only reviewed files by exact path. Never use broad adds or force-add ignored content.

```powershell
git add -- README.md README.zh-CN.md
# Add each other reviewed public path explicitly.
pwsh -NoProfile -File .\scripts\Test-PublicRelease.ps1 -Staged
git diff --cached --check
git diff --cached --name-only
git diff --cached
```

The policy allows only declared public paths and checks required files, private path patterns, databases, attachment and media extensions, recognizable binary/media signatures, document media syntax, secret patterns, and personal contact patterns. `-PolicySelfTest` exercises positive and negative policy fixtures without touching the real Git index:

```powershell
pwsh -NoProfile -File .\scripts\Test-PublicRelease.ps1 -PolicySelfTest
```

A passing check reduces accidental exposure; it is not proof that prose is anonymous. Review every staged line. Never bypass a failure, and never restore or generate a real private material file in the index.

For responsible reporting, follow [SECURITY.md](../SECURITY.md).
