from __future__ import annotations

import pytest

from backend.mail.credentials import (
    CredentialNotFound,
    CredentialValueTooLarge,
    SecureStorageUnavailable,
    WindowsCredentialStore,
    credential_target,
)


class FakeWinError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code, "fake")
        self.winerror = code


class FakeWinCred:
    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2

    def __init__(self) -> None:
        self.values: dict[str, dict] = {}
        self.writes: list[tuple[dict, int]] = []

    def CredWrite(self, value: dict, flags: int) -> None:
        self.values[value["TargetName"]] = value
        self.writes.append((value, flags))

    def CredRead(self, target: str, credential_type: int, flags: int) -> dict:
        del credential_type, flags
        if target not in self.values:
            raise FakeWinError(1168)
        return self.values[target]

    def CredDelete(self, target: str, credential_type: int, flags: int) -> None:
        del credential_type, flags
        if target not in self.values:
            raise FakeWinError(1168)
        del self.values[target]


def test_windows_credential_round_trip_uses_generic_local_machine() -> None:
    backend = FakeWinCred()
    store = WindowsCredentialStore(backend=backend, platform="win32")

    store.write("opaque-1", "person@invalid", "client-code")

    written, flags = backend.writes[0]
    assert flags == 0
    assert written["Type"] == backend.CRED_TYPE_GENERIC
    assert written["Persist"] == backend.CRED_PERSIST_LOCAL_MACHINE
    assert written["CredentialBlob"].startswith("CAA1:")
    assert "client-code" not in written["CredentialBlob"]
    assert written["TargetName"] == credential_target("opaque-1")
    assert store.read("opaque-1").username == "person@invalid"
    assert store.read("opaque-1").secret == "client-code"

    store.delete("opaque-1")
    with pytest.raises(CredentialNotFound):
        store.read("opaque-1")
    store.delete("opaque-1", missing_ok=True)


def test_windows_credential_read_accepts_native_utf16_blob_shapes() -> None:
    backend = FakeWinCred()
    store = WindowsCredentialStore(backend=backend, platform="win32")
    store.write("opaque-native", "person@invalid", "客户端-code")
    target = credential_target("opaque-native")
    encoded = backend.values[target]["CredentialBlob"].encode("utf-16-le")

    for native_blob in (encoded, encoded.decode("latin-1")):
        backend.values[target]["CredentialBlob"] = native_blob
        assert store.read("opaque-native").secret == "客户端-code"


def test_credential_store_fails_closed_off_windows() -> None:
    with pytest.raises(SecureStorageUnavailable):
        WindowsCredentialStore(backend=FakeWinCred(), platform="linux")


def test_credential_rejects_invalid_target_and_oversized_blob() -> None:
    backend = FakeWinCred()
    store = WindowsCredentialStore(backend=backend, platform="win32")
    with pytest.raises(ValueError):
        credential_target("../unsafe")
    with pytest.raises(CredentialValueTooLarge):
        store.write("opaque", "person@invalid", "x" * 2561)
    assert backend.writes == []
