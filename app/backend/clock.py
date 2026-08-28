"""Asia/Shanghai clock helpers for all stored timestamps."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

CN_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat(timespec="milliseconds")


def today_date() -> str:
    return datetime.now(CN_TZ).strftime("%Y-%m-%d")
