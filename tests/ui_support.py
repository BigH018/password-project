"""UI test fixtures (loaded as a pytest plugin by tests/conftest.py).

Qt runs off-screen so no windows appear.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading  # noqa: E402
from collections.abc import Callable, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from conftest import FAST_KDF, MASTER  # noqa: E402
from fake_data import make_account, make_game  # noqa: E402
from vaultkeeper.core.vault_service import VaultService  # noqa: E402
from vaultkeeper.crypto.kdf import KdfParams, derive_key  # noqa: E402
from vaultkeeper.ui.qt_adapters import QtTaskRunner  # noqa: E402


class Gate:
    """A key-derivation wrapper that blocks until released (simulates slow/hung Argon2)."""

    def __init__(self) -> None:
        self.event = threading.Event()
        self.entered = threading.Event()

    def kdf(self, password: str, salt: bytes, params: KdfParams) -> bytearray:
        self.entered.set()
        self.event.wait(timeout=10)
        return derive_key(password, salt, params)

    def release(self) -> None:
        self.event.set()


@pytest.fixture
def gate() -> Iterator[Gate]:
    g = Gate()
    yield g
    g.release()  # never leave a worker blocked


@pytest.fixture
def qt_runner(qapp: Any) -> QtTaskRunner:
    return QtTaskRunner()


@pytest.fixture
def make_qt_service(qt_runner: QtTaskRunner, vault_path: Path) -> Callable[..., VaultService]:
    """VaultService wired to the real Qt runner, with fast KDF and no delays."""

    def factory(**overrides: Any) -> VaultService:
        path = overrides.pop("path", vault_path)
        options: dict[str, Any] = {
            "runner": qt_runner,
            "kdf_params": FAST_KDF,
            "wrong_password_delay": 0.0,
            "sleep": lambda _s: None,
        }
        options.update(overrides)
        return VaultService(path, **options)

    return factory


@pytest.fixture
def existing_vault(vault_path: Path) -> Path:
    """A vault on disk (password MASTER) that also has a valid .bak."""
    svc = VaultService(vault_path, kdf_params=FAST_KDF)
    svc.create(MASTER)
    game = make_game()
    svc.data.games.append(game)
    svc.data.accounts.append(make_account(game))
    svc.save()
    svc.lock()
    return vault_path
