"""Shared fixtures. The network block is autouse: any network attempt fails the test."""

from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from fake_data import make_vault
from vaultkeeper.core.models import VaultData
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.crypto.kdf import KdfParams
from vaultkeeper.errors import VaultIOError

# Qt fixtures for tests/ui (off-screen), plus the fixtures shared by split test files.
pytest_plugins = ["ui_support", "backup_helpers", "vault_file_helpers"]


class NetworkBlockedError(RuntimeError):
    """Raised when code under test tries to use the network."""


def _blocked(*_args: Any, **_kwargs: Any) -> Any:
    raise NetworkBlockedError("Network access is forbidden in VaultKeeper tests.")


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make every outbound connection or DNS lookup raise."""
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    yield


@pytest.fixture
def fake_vault() -> VaultData:
    """A small vault of obviously fake data."""
    return make_vault()


class FakeStore:
    """In-memory VaultStore: counts saves and can be told to fail."""

    def __init__(self, data: VaultData | None = None) -> None:
        self.data = data if data is not None else VaultData.empty()
        self.saves = 0
        self.fail_next_save = False

    def save(self) -> None:
        if self.fail_next_save:
            self.fail_next_save = False
            raise VaultIOError("Simulated save failure.")
        self.data.updated_at = "2026-10-01T12:00:00+00:00"
        self.saves += 1


@pytest.fixture
def store() -> FakeStore:
    """An empty in-memory store."""
    return FakeStore()


# Tiny Argon2 cost so the suite stays fast. Production params run only under -m slow.
FAST_KDF = KdfParams(time_cost=1, memory_kib=8 * 1024, parallelism=1)
MASTER = "fake master passphrase one"
OTHER_MASTER = "another fake passphrase two"


@pytest.fixture
def fast_kdf() -> KdfParams:
    """Minimal-cost KDF parameters."""
    return FAST_KDF


@pytest.fixture
def vault_path(tmp_path: Path) -> Path:
    """Location for a test vault (inside pytest's temp dir, never the real one)."""
    return tmp_path / "test.vault"


@pytest.fixture
def make_service(vault_path: Path) -> Callable[..., VaultService]:
    """Factory for VaultService with fast KDF params and no real sleeping."""

    def factory(**overrides: Any) -> VaultService:
        path = overrides.pop("path", vault_path)
        options: dict[str, Any] = {
            "kdf_params": FAST_KDF,
            "wrong_password_delay": 0.0,
            "sleep": lambda _s: None,
        }
        options.update(overrides)
        return VaultService(path, **options)

    return factory
