"""Run the career application board API and built frontend on loopback."""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from backend.app import create_app, init_database  # noqa: E402
from backend.config import default_paths  # noqa: E402
from backend.database import DatabaseUnavailableError  # noqa: E402
from backend.mail.legacy_outlook import purge_legacy_outlook_cache  # noqa: E402


BUILD_HINT = """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>求职投递助手 / Career Application Assistant</title>
    <style>
      body {
        margin: 0;
        min-width: 320px;
        font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
        background: #ffffff;
        color: #111b34;
      }
      .shell { max-width: 960px; margin: 0 auto; padding: 48px 24px; }
      h1 { font-size: 28px; line-height: 36px; margin: 0 0 16px; }
      p { color: #68758a; line-height: 22px; font-size: 14px; }
      code { font-size: 13px; color: #111b34; }
    </style>
  </head>
  <body>
    <main class="shell">
      <h1>求职投递助手 / Career Application Assistant</h1>
      <p>The board API is running at <code>/api</code>, but the production frontend build is missing.</p>
      <p>Build the frontend first: <code>pnpm --dir app/frontend install</code> and <code>pnpm --dir app/frontend build</code>, then restart this service.</p>
    </main>
  </body>
</html>
"""


def main() -> None:
    paths = default_paths()

    if not paths.private_root.is_dir():
        print(
            "The private/ overlay is missing. "
            "Run scripts/Initialize-PrivateOverlay.ps1 first."
        )
        sys.exit(1)

    try:
        purge_legacy_outlook_cache()
        init_database(paths)
    except (DatabaseUnavailableError, Exception) as exc:
        print(f"Unable to initialize the local database: {exc}")
        sys.exit(1)

    if not paths.frontend_dist.is_dir():
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse

        app = create_app()

        @app.get("/", include_in_schema=False)
        def build_hint() -> HTMLResponse:
            return HTMLResponse(BUILD_HINT)

    else:
        app = create_app()

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
