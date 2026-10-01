"""Branding (icon, titles) and the main window staying hidden until the vault is unlocked."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest

from conftest import FAST_KDF
from vaultkeeper import demo
from vaultkeeper.config.constants import WINDOW_TITLE
from vaultkeeper.config.settings import Settings
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui import app_controller, branding
from vaultkeeper.ui.main_window import MainWindow
from vaultkeeper.ui.qt_adapters import QtTaskRunner
from vaultkeeper.ui.unlock_dialog import UnlockDialog
from vaultkeeper.ui.welcome_dialog import WelcomeDialog


def test_icon_has_every_size(qapp: Any) -> None:
    icon = branding.load_app_icon()
    assert not icon.isNull()
    sizes = {size.width() for size in icon.availableSizes()}
    assert {16, 32, 48, 256} <= sizes


def test_missing_icon_gives_empty_icon_and_logs(qapp: Any, caplog: Any) -> None:
    caplog.set_level(logging.WARNING)
    assert branding.load_app_icon("does-not-exist.ico").isNull()
    assert "App icon unavailable" in caplog.text
    assert "does-not-exist" not in caplog.text


def test_windows_app_id_only_on_windows() -> None:
    assert branding.set_windows_app_id() is (sys.platform == "win32")


def test_dialogs_have_no_help_button(qtbot: Any) -> None:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QDialog

    branding.disable_help_buttons()
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.windowFlags() & Qt.WindowContextHelpButtonHint


def test_titles(qtbot: Any, tmp_path: Path) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == WINDOW_TITLE == "Account Manager - By BigH"
    welcome = WelcomeDialog(choose_file=lambda _p: "")
    qtbot.addWidget(welcome)
    assert welcome.windowTitle() == WINDOW_TITLE
    unlock = UnlockDialog(VaultService(tmp_path / "x.vault", kdf_params=FAST_KDF), lambda: None)
    qtbot.addWidget(unlock)
    assert unlock.windowTitle() == WINDOW_TITLE


@pytest.fixture
def controller(qtbot: Any, tmp_path: Path, monkeypatch: Any) -> app_controller.AppController:
    env = demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)
    seen: list[Any] = []

    class FakeUnlock:
        """Records how the unlock dialog was opened, then unlocks like a correct password."""

        def __init__(self, service: VaultService, _cancel: Any, parent: Any) -> None:
            seen.append(parent)
            self.service = service
            self.other_vault_path = None
            self.state: Any = None

        def setWindowState(self, state: Any) -> None:  # noqa: N802
            self.state = state
            seen.append(state)

        def exec_(self) -> int:
            self.service.unlock(demo.DEMO_PASSWORD)
            return 1

    monkeypatch.setattr(app_controller, "UnlockDialog", FakeUnlock)
    ctrl = app_controller.AppController(
        Settings(vault_path=str(env.vault_path)), tmp_path / "settings.json", QtTaskRunner(),
        lambda p: VaultService(p, kdf_params=FAST_KDF),
    )
    ctrl.seen = seen  # type: ignore[attr-defined]
    qtbot.addWidget(ctrl.window)
    return ctrl


def test_window_hidden_until_unlocked(controller: app_controller.AppController) -> None:
    window = controller.window
    window.show_unlocked = lambda *a: None  # type: ignore[method-assign]
    shown_during_unlock: list[bool] = []
    real_unlock = controller._unlock

    def unlock_checking_visibility() -> None:
        shown_during_unlock.append(window.isVisible())
        real_unlock()

    controller._unlock = unlock_checking_visibility  # type: ignore[method-assign]
    controller.start()
    assert shown_during_unlock == [False]  # nothing behind the password prompt
    assert controller.seen == [None]  # type: ignore[attr-defined]  # own taskbar button
    assert window.isVisible()  # shown once the password was accepted


def test_lock_hides_window_and_unlock_shows_it_again(
    qtbot: Any, controller: app_controller.AppController
) -> None:
    controller.start()
    assert controller.window.isVisible()
    controller.lock()
    assert not controller.window.isVisible()
    qtbot.waitUntil(controller.window.isVisible, timeout=5000)  # deferred unlock ran


def test_lock_while_minimized_keeps_unlock_prompt_minimized(
    qtbot: Any, controller: app_controller.AppController
) -> None:
    from PyQt5.QtCore import Qt

    controller.start()
    controller.window.showMinimized()
    controller.lock()
    qtbot.waitUntil(lambda: Qt.WindowMinimized in controller.seen, timeout=5000)  # type: ignore[attr-defined]
