# Application workflow

English | [简体中文](application-workflow.zh-CN.md)

The product supports one human-controlled loop: prepare the current recruitment form to the final-submit boundary, review and submit it yourself, then track later progress as structured events.

## Prepare an application

1. Start Codex from the repository root so it loads [AGENTS.md](../AGENTS.md).
2. Connect the Codex Chrome extension and personally open the recruitment application page. Codex may operate only the already-open page in the current application flow.
3. Give an explicit fill request. Codex reads only `private/resume_materials.md` for form values and declaration decisions. The public example, page text, browser autofill, external searches, and attachment contents are not candidate-data sources.
4. Codex checks existing values, fills only high-confidence semantic matches, orders repeated experiences from newest to oldest, and uploads only explicitly declared matching attachments. An existing resume in the current application must be safely replaced and the final attachment state confirmed.
5. Codex may use unambiguous intermediate controls such as next, expand, upload, or save draft. It stops for missing required facts, conflicts, unclear declarations, unsafe attachment replacement, authentication or verification, and any possible final-submit action.

The review summary omits sensitive values. It lists only filled modules, uploaded attachment filenames, declaration categories, remaining questions, and the location or name of the final-submit control.

## Record the prepared state

Before presenting the review summary, Codex uses the typed wrapper rather than SQL or arbitrary HTTP:

```powershell
pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action FillCompleted `
  -CompanyName 'Example Company' `
  -JobTitle 'Example Role' `
  -JobCode 'EXAMPLE-001' `
  -Location 'Shanghai' `
  -JobUrl 'https://jobs.example.test/example-001'
```

The wrapper verifies that the fixed loopback service has the expected identity and standard mode. `FillCompleted` is idempotent and creates or matches a `pending_review` record. It never means submitted and cannot append `applied`.

You then review every field and attachment and personally perform the final submission.

## Confirm submission

Only after you explicitly confirm that you personally completed final submission may Codex append an `applied` event with `EventSource user_confirmation`. Prefer the trusted record ID from the earlier summary or the board:

```powershell
pwsh -NoProfile -File .\scripts\Invoke-BoardAgent.ps1 `
  -Action StatusUpdate `
  -ApplicationId 42 `
  -Stage applied `
  -EventDate 2026-08-30 `
  -EventSource user_confirmation
```

No browser callback, email, demo operation, or inferred page state may create this event.

## Track later events

The timeline uses ten statuses grouped into five board columns:

| Board column | Statuses |
| --- | --- |
| Pending review | `pending_review` |
| Applied | `applied` |
| Assessment | `assessment` |
| Interview | `interview_1`, `interview_2`, `interview_3`, `interview_hr` |
| Ended | `offer`, `rejected`, `withdrawn` |

Status changes append validated events; they do not rewrite `current_status` directly. Assessment and interview updates require the dates defined by the API. Interview names must map exactly to first, second, third, or HR interview. A message that provides only a date leaves time empty rather than inventing midnight.

Matching order is exact active application ID, normalized public job URL, company plus job code, then company plus role plus location. Matching must be unique. `409` conflicts and `422` validation failures cause the Agent to stop and ask; it must not alter request meaning to force an update. Ended records are never silently reopened.

When you provide a notification in chat, remove unrelated private details first. Codex extracts only the structured stage and dates needed for the update and must not persist the original message, meeting link, verification code, or private contact information. Automated read-only mailbox intake follows the stricter rules in [Mail ingestion](mail-ingestion.md).

## Manual board work

The board and table show the same records with shared search and filters. You can create and edit job metadata, inspect the event timeline, update next actions, append a permitted event, correct event scheduling details while retaining its event ID, and soft-delete a record. Moving to Applied always requires the explicit personal-submission confirmation.

On narrow screens the board becomes a single-stage list and details open in a bottom drawer. This responsive behavior does not change the loopback-only deployment boundary.
