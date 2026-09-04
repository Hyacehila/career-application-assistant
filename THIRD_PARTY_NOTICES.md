# Third-party software notices

This project uses third-party packages through the normal Python and npm dependency mechanisms. It does not copy or embed the source code of a complete mail client. Exact resolved versions and transitive packages are recorded in `uv.lock` and `app/frontend/pnpm-lock.yaml`; each package remains governed by its own license.

The mailbox-ingestion implementation particularly relies on:

| Package | Use in this project | Upstream | License |
| --- | --- | --- | --- |
| IMAPClient | Parsed UID-based IMAP operations over TLS | [mjs/imapclient](https://github.com/mjs/imapclient) | BSD-3-Clause |
| APScheduler | Single-process periodic QQ/163 IMAP polling | [agronholm/apscheduler](https://github.com/agronholm/apscheduler) | MIT |
| dateparser | Constrained Chinese/English recruitment date parsing | [scrapinghub/dateparser](https://github.com/scrapinghub/dateparser) | BSD-3-Clause |
| HTTPX | Development-only FastAPI test client transport | [encode/httpx](https://github.com/encode/httpx) | BSD-3-Clause |
| Beautiful Soup | Safe local HTML-to-text extraction after body-size checks | [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) | MIT |
| pywin32 | Windows Credential Manager access for IMAP authorization codes | [mhammond/pywin32](https://github.com/mhammond/pywin32) | PSF-2.0 |

Outlook access is supplied by the separately configured Codex Outlook Email connector and is not a Python runtime dependency. The local IMAP connector exposes no mutation primitive, and secure-storage failures never fall back to plaintext.
