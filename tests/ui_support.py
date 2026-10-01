"""UI test fixtures (loaded as a pytest plugin by tests/conftest.py).

Qt runs off-screen so no windows appear.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc  # noqa: E402
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


@pytest.fixture(autouse=True)
def no_real_message_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never open a real modal box in tests (one left open at teardown crashes Qt).

    Default: confirmations say yes, errors are swallowed. Tests that check a prompt override
    these with their own monkeypatch.
    """
    from vaultkeeper.ui import main_window, messages

    monkeypatch.setattr(messages, "confirm", lambda *_a, **_k: True)
    monkeypatch.setattr(messages, "show_error", lambda *_a, **_k: None)
    monkeypatch.setattr(messages, "show_warning", lambda *_a, **_k: None)
    monkeypatch.setattr(main_window, "confirm", lambda *_a, **_k: True)
    monkeypatch.setattr(main_window, "show_error", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def dispose_session_guards(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Shut down every SessionGuard a test made, then collect garbage at a safe point.

    A guard installs an app-wide event filter. Controllers live on in reference cycles, so
    without this the GC deletes their filters at a random moment in a LATER test, possibly
    while Qt is iterating the filter list: a Windows access violation.
    """
    from vaultkeeper.ui.session_guard import SessionGuard

    created: list[SessionGuard] = []
    original = SessionGuard.__init__

    def tracking_init(self: SessionGuard, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(SessionGuard, "__init__", tracking_init)
    yield
    for guard in created:
        guard.shutdown()
    created.clear()
    gc.collect()


@pytest.fixture(autouse=True)
def app_never_quits(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Stop tests from ending the shared QApplication.

    The controller's quit() calls QApplication.quit(). When pytest-qt closes a controller's
    window at teardown, that would stop event delivery for every later test.
    """
    from PyQt5.QtWidgets import QApplication

    calls: list[bool] = []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: calls.append(True)))
    return calls
