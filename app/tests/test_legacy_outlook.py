"""One-way cleanup tests for the retired local Outlook token cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.mail import legacy_outlook
from backend.mail.legacy_outlook import (
    LegacyOutlookCleanupError,
    legacy_cache_directory,
    purge_legacy_outlook_cache,
)


def _auth_dir(tmp_path: Path) -> Path:
    target = tmp_path / "CareerApplicationAssistant" / "auth"
    target.mkdir(parents=True)
    return target


def test_cleanup_removes_only_strict_legacy_names_and_is_idempotent(tmp_path: Path) -> None:
    target = _auth_dir(tmp_path)
    expected = {
        "msal.cache",
        "msal.cache.lockfile",
        "msal.0123456789abcdef0123456789abcdef.cache",
        "msal.abcdefabcdefabcdefabcdefabcdefab.backup.lockfile",
    }
    untouched = {
        "msal.cache.backup",
        "msal.short.cache",
        "notes.txt",
        "other-token.cache",
    }
    for name in expected | untouched:
        (target / name).write_text("synthetic", encoding="utf-8")

    removed = purge_legacy_outlook_cache(
        environ={"LOCALAPPDATA": str(tmp_path)}, platform="win32"
    )
    assert set(removed) == expected
    assert {item.name for item in target.iterdir()} == untouched
    assert purge_legacy_outlook_cache(
        environ={"LOCALAPPDATA": str(tmp_path)}, platform="win32"
    ) == ()


def test_cleanup_rejects_missing_or_out_of_bounds_local_app_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(LegacyOutlookCleanupError, match="local_app_data_unavailable"):
        legacy_cache_directory(environ={}, platform="win32")

    monkeypatch.setattr(legacy_outlook, "APPLICATION_NAME", "..")
    with pytest.raises(LegacyOutlookCleanupError, match="cache_path_unsafe"):
        legacy_cache_directory(
            environ={"LOCALAPPDATA": str(tmp_path / "root")}, platform="win32"
        )


def test_cleanup_refuses_matching_directory_and_stops_on_delete_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _auth_dir(tmp_path)
    (target / "msal.cache").mkdir()
    with pytest.raises(LegacyOutlookCleanupError, match="cache_target_invalid"):
        purge_legacy_outlook_cache(
            environ={"LOCALAPPDATA": str(tmp_path)}, platform="win32"
        )

    (target / "msal.cache").rmdir()
    cache = target / "msal.cache"
    cache.write_text("synthetic", encoding="utf-8")
    original_unlink = Path.unlink

    def fail_unlink(path: Path, *args, **kwargs) -> None:
        if path == cache:
            raise PermissionError("synthetic locked file")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(LegacyOutlookCleanupError, match="cache_delete_failed"):
        purge_legacy_outlook_cache(
            environ={"LOCALAPPDATA": str(tmp_path)}, platform="win32"
        )
    assert cache.exists()


def test_cleanup_is_a_noop_off_windows(tmp_path: Path) -> None:
    target = _auth_dir(tmp_path)
    cache = target / "msal.cache"
    cache.write_text("synthetic", encoding="utf-8")
    assert purge_legacy_outlook_cache(
        environ={"LOCALAPPDATA": str(tmp_path)}, platform="linux"
    ) == ()
    assert cache.exists()
