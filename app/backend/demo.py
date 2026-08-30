"""Isolated synthetic Demo data and temporary-directory safety checks."""

from __future__ import annotations

import re
import shutil
import stat
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import store
from .clock import CN_TZ
from .config import Paths
from .schemas import CreateApplication, CreateEvent

DEMO_DIRECTORY_RE = re.compile(r"^career-application-assistant-demo-[0-9a-f]{32}$")


class UnsafeDemoDirectoryError(ValueError):
    """Raised when Demo storage is not an owned system-temp session directory."""


def _is_reparse_point(path: Path) -> bool:
    attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & marker)


def validate_demo_directory(directory: Path) -> Path:
    """Validate and return a real, direct child of the system temporary root."""

    candidate = directory.absolute()
    temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
    if not DEMO_DIRECTORY_RE.fullmatch(candidate.name):
        raise UnsafeDemoDirectoryError("Demo directory name is invalid.")
    if candidate.parent.resolve(strict=True) != temp_root:
        raise UnsafeDemoDirectoryError("Demo directory must be a direct system-temp child.")
    if not candidate.exists() or not candidate.is_dir():
        raise UnsafeDemoDirectoryError("Demo directory does not exist.")
    is_junction = getattr(candidate, "is_junction", lambda: False)
    if candidate.is_symlink() or is_junction() or _is_reparse_point(candidate):
        raise UnsafeDemoDirectoryError("Demo directory must not be a link or junction.")
    resolved = candidate.resolve(strict=True)
    if resolved.parent != temp_root or resolved.name != candidate.name:
        raise UnsafeDemoDirectoryError("Demo directory resolved outside system temp.")
    return resolved


def validate_demo_paths(paths: Paths) -> Path:
    """Validate the only writable location accepted by the Demo factory."""

    return validate_demo_directory(paths.private_root)


def cleanup_demo_directory(directory: Path) -> None:
    """Remove one validated Demo session without following replacement links."""

    validated = validate_demo_directory(directory)
    shutil.rmtree(validated)


def _iso(day: date, offset: int) -> str:
    return (day + timedelta(days=offset)).isoformat()


def _application(
    day: date,
    *,
    company: str,
    role: str,
    slug: str,
    offset: int,
    application_type: str,
    location: str,
    next_action: str | None = None,
    next_action_offset: int | None = None,
) -> CreateApplication:
    return CreateApplication(
        company_name=company,
        job_title=role,
        application_type=application_type,
        location=location,
        source="合成演示",
        job_url=f"https://{slug}.example.test/jobs/demo",
        next_action=next_action,
        next_action_date=(
            _iso(day, next_action_offset) if next_action_offset is not None else None
        ),
        notes="合成演示记录，不对应真实公司或岗位。",
        event_date=_iso(day, offset),
    )


def reset_demo_data(paths: Paths, *, today: date | None = None) -> int:
    """Atomically replace Demo records with six deterministic synthetic examples."""

    validate_demo_paths(paths)
    anchor = today or datetime.now(CN_TZ).date()
    records: list[tuple[CreateApplication, list[CreateEvent]]] = [
        (
            _application(
                anchor,
                company="星尘示例科技（虚构）",
                role="前端工程师（演示）",
                slug="stardust",
                offset=-1,
                application_type="校招",
                location="上海",
                next_action="人工复核演示申请",
                next_action_offset=1,
            ),
            [],
        ),
        (
            _application(
                anchor,
                company="云帆示例网络（虚构）",
                role="产品助理（演示）",
                slug="cloudsail",
                offset=-8,
                application_type="实习",
                location="北京",
            ),
            [
                CreateEvent(
                    stage="applied",
                    event_date=_iso(anchor, -7),
                    source="user_confirmation",
                    note="合成演示事件。",
                )
            ],
        ),
        (
            _application(
                anchor,
                company="青禾示例数据（虚构）",
                role="数据分析师（演示）",
                slug="greenfield",
                offset=-14,
                application_type="社招",
                location="杭州",
                next_action="完成演示测评",
                next_action_offset=2,
            ),
            [
                CreateEvent(
                    stage="applied",
                    event_date=_iso(anchor, -13),
                    source="user_confirmation",
                ),
                CreateEvent(
                    stage="assessment",
                    event_date=_iso(anchor, -2),
                    deadline_date=_iso(anchor, 2),
                    source="manual_ui",
                    note="合成演示测评。",
                ),
            ],
        ),
        (
            _application(
                anchor,
                company="远山示例智能（虚构）",
                role="算法工程师（演示）",
                slug="farhill",
                offset=-24,
                application_type="校招",
                location="深圳",
                next_action="参加演示二面",
                next_action_offset=1,
            ),
            [
                CreateEvent(
                    stage="applied",
                    event_date=_iso(anchor, -23),
                    source="user_confirmation",
                ),
                CreateEvent(
                    stage="interview_1",
                    event_date=_iso(anchor, -12),
                    scheduled_date=_iso(anchor, -10),
                    mode="online",
                    source="manual_ui",
                ),
                CreateEvent(
                    stage="interview_2",
                    event_date=_iso(anchor, -1),
                    scheduled_date=_iso(anchor, 1),
                    mode="online",
                    source="manual_ui",
                    note="合成演示面试。",
                ),
            ],
        ),
        (
            _application(
                anchor,
                company="白露示例设计（虚构）",
                role="体验设计师（演示）",
                slug="whitedew",
                offset=-35,
                application_type="社招",
                location="广州",
            ),
            [
                CreateEvent(
                    stage="applied",
                    event_date=_iso(anchor, -34),
                    source="user_confirmation",
                ),
                CreateEvent(
                    stage="offer",
                    event_date=_iso(anchor, -3),
                    source="manual_ui",
                    note="合成演示 Offer。",
                ),
            ],
        ),
        (
            _application(
                anchor,
                company="萤火示例系统（虚构）",
                role="测试工程师（演示）",
                slug="firefly",
                offset=-28,
                application_type="其他",
                location="成都",
            ),
            [
                CreateEvent(
                    stage="applied",
                    event_date=_iso(anchor, -27),
                    source="user_confirmation",
                ),
                CreateEvent(
                    stage="rejected",
                    event_date=_iso(anchor, -4),
                    source="manual_ui",
                    note="合成演示结束事件。",
                ),
            ],
        ),
    ]

    with store.open_connection_tx(paths) as connection:
        connection.execute("DELETE FROM mail_event_candidates")
        connection.execute("DELETE FROM mail_sync_cursors")
        connection.execute("DELETE FROM mail_accounts")
        connection.execute("DELETE FROM application_events")
        connection.execute("DELETE FROM applications")
        connection.execute(
            "DELETE FROM sqlite_sequence WHERE name IN ('applications', 'application_events', 'mail_event_candidates')"
        )
        for application_payload, events in records:
            application = store.create_application(connection, application_payload)
            for event in events:
                store.add_event(connection, application.id, event)
    return len(records)
