"""One-way cleanup for the retired local Outlook Graph token cache."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Mapping

APPLICATION_NAME = "CareerApplicationAssistant"
_STAGING_CACHE_RE = re.compile(
    r"^msal\.[0-9a-f]{32}\.(?:cache|backup)(?:\.lockfile)?$"
)
_FIXED_CACHE_NAMES = frozenset({"msal.cache", "msal.cache.lockfile"})


class LegacyOutlookCleanupError(RuntimeError):
    """Raised when the retired cache cannot be inspected or removed safely."""


def legacy_cache_directory(
    *, environ: Mapping[str, str] | None = None, platform: str | None = None
) -> Path | None:
    """Resolve the exact legacy cache directory, or return ``None`` off Windows."""

    current_platform = sys.platform if platform is None else platform
    if current_platform != "win32":
        return None
    variables = os.environ if environ is None else environ
    local_app_data = variables.get("LOCALAPPDATA")
    if not local_app_data:
        raise LegacyOutlookCleanupError("legacy_outlook_local_app_data_unavailable")
    root = Path(local_app_data).resolve(strict=False)
    target = (root / APPLICATION_NAME / "auth").resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise LegacyOutlookCleanupError("legacy_outlook_cache_path_unsafe") from exc
    return target


def purge_legacy_outlook_cache(
    *, environ: Mapping[str, str] | None = None, platform: str | None = None
) -> tuple[str, ...]:
    """Delete only known legacy MSAL cache names and return removed file names."""

    directory = legacy_cache_directory(environ=environ, platform=platform)
    if directory is None or not directory.exists():
        return ()
    if not directory.is_dir():
        raise LegacyOutlookCleanupError("legacy_outlook_cache_path_invalid")
    try:
        children = tuple(directory.iterdir())
    except OSError as exc:
        raise LegacyOutlookCleanupError("legacy_outlook_cache_inspection_failed") from exc

    targets = tuple(
        child
        for child in children
        if child.name in _FIXED_CACHE_NAMES or _STAGING_CACHE_RE.fullmatch(child.name)
    )
    removed: list[str] = []
    for target in targets:
        if target.is_dir() and not target.is_symlink():
            raise LegacyOutlookCleanupError("legacy_outlook_cache_target_invalid")
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            raise LegacyOutlookCleanupError("legacy_outlook_cache_delete_failed") from exc
        removed.append(target.name)
    return tuple(removed)


__all__ = [
    "LegacyOutlookCleanupError",
    "legacy_cache_directory",
    "purge_legacy_outlook_cache",
]
