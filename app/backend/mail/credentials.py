"""Windows-only credential and encrypted MSAL cache helpers.

This module deliberately imports optional Windows dependencies lazily.  The
mail feature must fail closed when Windows Credential Manager or DPAPI cannot
be used; it must never fall back to a plaintext file or an in-memory cache in
production.
"""

from __future__ import annotations

import base64
import binascii
import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any


APPLICATION_NAME = "CareerApplicationAssistant"
IMAP_TARGET_PREFIX = f"{APPLICATION_NAME}/mail"
MAX_CREDENTIAL_BLOB_BYTES = 2560
_CREDENTIAL_VALUE_PREFIX = "CAA1:"


class CredentialStoreError(RuntimeError):
    """Base class for safe, non-secret-bearing credential errors."""


class SecureStorageUnavailable(CredentialStoreError):
    """Raised when the required Windows secure-storage backend is unavailable."""


class CredentialNotFound(CredentialStoreError):
    """Raised when a requested credential does not exist."""


class CredentialValueTooLarge(CredentialStoreError):
    """Raised before WinCred's Generic Credential blob limit is exceeded."""


@dataclass(frozen=True, slots=True)
class StoredCredential:
    """A credential loaded from Windows Credential Manager."""

    username: str
    secret: str


def _is_windows(platform: str | None = None) -> bool:
    return (platform or sys.platform).lower().startswith("win")


def _load_optional_module(name: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except (ImportError, OSError) as exc:
        raise SecureStorageUnavailable("Windows secure storage is unavailable.") from exc


def credential_target(account_id: str) -> str:
    """Return the fixed WinCred target name for an opaque local account id."""

    cleaned = account_id.strip()
    if not cleaned or any(char in cleaned for char in ("/", "\\", "\x00")):
        raise ValueError("account_id must be a non-empty opaque identifier")
    return f"{IMAP_TARGET_PREFIX}/{cleaned}/imap"


class WindowsCredentialStore:
    """Narrow Generic Credential wrapper for IMAP authorization codes."""

    def __init__(
        self,
        *,
        backend: ModuleType | Any | None = None,
        platform: str | None = None,
    ) -> None:
        if not _is_windows(platform):
            raise SecureStorageUnavailable("Windows Credential Manager is required.")
        self._backend = backend or _load_optional_module("win32cred")

    def write(self, account_id: str, username: str, secret: str) -> None:
        target = credential_target(account_id)
        normalized_username = username.strip()
        if not normalized_username or "\x00" in normalized_username:
            raise ValueError("username must be non-empty")
        if not secret or "\x00" in secret:
            raise ValueError("secret must be non-empty")

        # pywin32's Unicode CredWrite wrapper accepts CredentialBlob as text.
        # A versioned ASCII envelope makes its varying bytes/str CredRead
        # representations unambiguous while still leaving encryption entirely
        # to Windows Credential Manager.
        credential_value = _encode_credential_value(secret)
        blob = credential_value.encode("utf-16-le")
        if len(blob) > MAX_CREDENTIAL_BLOB_BYTES:
            raise CredentialValueTooLarge("Credential value exceeds the Windows limit.")

        credential = {
            "Type": self._constant("CRED_TYPE_GENERIC", 1),
            "TargetName": target,
            "UserName": normalized_username,
            "CredentialBlob": credential_value,
            "Persist": self._constant("CRED_PERSIST_LOCAL_MACHINE", 2),
            "Comment": f"{APPLICATION_NAME} IMAP authorization code",
        }
        try:
            self._backend.CredWrite(credential, 0)
        except Exception as exc:  # pywin32 exposes platform-specific error classes
            raise CredentialStoreError("Could not write the Windows credential.") from exc

    def read(self, account_id: str) -> StoredCredential:
        target = credential_target(account_id)
        try:
            value = self._backend.CredRead(
                target,
                self._constant("CRED_TYPE_GENERIC", 1),
                0,
            )
        except Exception as exc:
            if self._is_not_found_error(exc):
                raise CredentialNotFound("Credential does not exist.") from exc
            raise CredentialStoreError("Could not read the Windows credential.") from exc

        username = str(value.get("UserName") or "")
        blob = value.get("CredentialBlob", b"")
        try:
            secret = _decode_credential_value(blob)
        except (UnicodeDecodeError, UnicodeEncodeError, binascii.Error, ValueError) as exc:
            raise CredentialStoreError("Stored credential has an invalid encoding.") from exc
        if not username or not secret:
            raise CredentialStoreError("Stored credential is incomplete.")
        return StoredCredential(username=username, secret=secret)

    def delete(self, account_id: str, *, missing_ok: bool = True) -> None:
        target = credential_target(account_id)
        try:
            self._backend.CredDelete(
                target,
                self._constant("CRED_TYPE_GENERIC", 1),
                0,
            )
        except Exception as exc:
            if missing_ok and self._is_not_found_error(exc):
                return
            if self._is_not_found_error(exc):
                raise CredentialNotFound("Credential does not exist.") from exc
            raise CredentialStoreError("Could not delete the Windows credential.") from exc

    def _constant(self, name: str, fallback: int) -> int:
        return int(getattr(self._backend, name, fallback))

    @staticmethod
    def _is_not_found_error(exc: Exception) -> bool:
        # winerror 1168 is ERROR_NOT_FOUND.  pywintypes.error normally exposes
        # it both as .winerror and as the first positional argument.
        code = getattr(exc, "winerror", None)
        if code is None and exc.args:
            code = exc.args[0]
        return code == 1168


def _encode_credential_value(secret: str) -> str:
    encoded = base64.urlsafe_b64encode(secret.encode("utf-8")).decode("ascii")
    return f"{_CREDENTIAL_VALUE_PREFIX}{encoded}"


def _decode_credential_value(blob: object) -> str:
    if isinstance(blob, bytes):
        if len(blob) % 2 == 0 and b"\x00" in blob:
            text = blob.decode("utf-16-le")
        else:
            text = blob.decode("utf-8")
    else:
        text = str(blob)
        if "\x00" in text:
            text = text.encode("latin-1").decode("utf-16-le")
    if not text.startswith(_CREDENTIAL_VALUE_PREFIX):
        # Compatibility with a credential written by an older backend that
        # returned the original text directly.
        return text
    payload = text[len(_CREDENTIAL_VALUE_PREFIX) :]
    raw = base64.b64decode(payload.encode("ascii"), altchars=b"-_", validate=True)
    return raw.decode("utf-8")


def default_msal_cache_path(*, environ: dict[str, str] | None = None) -> Path:
    """Return a cache path under LocalAppData without a plaintext fallback."""

    variables = os.environ if environ is None else environ
    local_app_data = variables.get("LOCALAPPDATA")
    if not local_app_data:
        raise SecureStorageUnavailable("LOCALAPPDATA is unavailable.")
    return Path(local_app_data) / APPLICATION_NAME / "auth" / "msal.cache"


def create_dpapi_token_cache(
    cache_path: str | Path | None = None,
    *,
    extensions_module: ModuleType | Any | None = None,
    platform: str | None = None,
) -> Any:
    """Create a DPAPI-encrypted, lock-aware MSAL token cache.

    ``FilePersistenceWithDataProtection`` is selected explicitly.  In
    particular, this helper does not call a generic persistence builder that
    could choose a plaintext implementation on another platform.
    """

    if not _is_windows(platform):
        raise SecureStorageUnavailable("Windows DPAPI is required for Outlook tokens.")
    module = extensions_module or _load_optional_module("msal_extensions")
    persistence_type = getattr(module, "FilePersistenceWithDataProtection", None)
    cache_type = getattr(module, "PersistedTokenCache", None)
    if persistence_type is None or cache_type is None:
        raise SecureStorageUnavailable("DPAPI token-cache support is unavailable.")

    location = Path(cache_path) if cache_path is not None else default_msal_cache_path()
    try:
        location.parent.mkdir(parents=True, exist_ok=True)
        persistence = persistence_type(str(location))
        # Eagerly probe availability where supported.  The implementation
        # normally exposes this as a boolean property.
        available = getattr(persistence, "is_available", True)
        if callable(available):
            available = available()
        if available is False:
            raise SecureStorageUnavailable("Windows DPAPI is unavailable.")
        return cache_type(persistence)
    except SecureStorageUnavailable:
        raise
    except Exception as exc:
        raise SecureStorageUnavailable("Could not initialize the encrypted token cache.") from exc


__all__ = [
    "APPLICATION_NAME",
    "CredentialNotFound",
    "CredentialStoreError",
    "CredentialValueTooLarge",
    "SecureStorageUnavailable",
    "StoredCredential",
    "WindowsCredentialStore",
    "create_dpapi_token_cache",
    "credential_target",
    "default_msal_cache_path",
]
