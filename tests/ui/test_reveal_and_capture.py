"""SEC-Low6: "Show passwords" turns itself off; optional exclusion from screen capture."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtWidgets import QDialog

from conftest import FAST_KDF
from vaultkeeper import demo
from vaultkeeper.config import constants as c
from vaultkeeper.config.settings import Settings
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui import main_window as mw
from vaultkeeper.ui import qt_adapters
from vaultkeeper.ui.session_guard import SessionGuard
from vaultkeeper.ui.settings_dialog import SettingsDialog
from vaultkeeper.ui.widgets.account_table import MASK


@pytest.fixture
def window(qtbot: Any, tmp_path: Path) -> mw.MainWindow:
    env = demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock(demo.DEMO_PASSWORD)
    win = mw.MainWindow()
    qtbot.addWidget(win)
    win.show_unlocked(str(svc.path), False, AccountService(svc), GameService(svc))
    return win


def _password_cell(window: mw.MainWindow) -> str:
    model = window.panel.model
    column = next(i for i in range(model.columnCount())
                  if model.headerData(i, 1) == "Password")
    return str(model.index(0, column).data())


# --- Show passwords switches itself off -------------------------------------------------


def test_show_passwords_hides_again_after_the_timeout(window: mw.MainWindow) -> None:
    timer = window.panel.reveal_timer
    window.panel.set_reveal_seconds(30)
    window.show_passwords_action.setChecked(True)
    assert _password_cell(window) != MASK
    assert timer.isActive() and timer.interval() == 30_000 and timer.isSingleShot()
    timer.timeout.emit()  # 30 s later
    assert not window.show_passwords_action.isChecked()
    assert _password_cell(window) == MASK


def test_hiding_by_hand_stops_the_timer(window: mw.MainWindow) -> None:
    window.show_passwords_action.setChecked(True)
    window.show_passwords_action.setChecked(False)
    assert not window.panel.reveal_timer.isActive()


def test_lock_hides_passwords_and_stops_the_timer(window: mw.MainWindow) -> None:
    window.show_passwords_action.setChecked(True)
    window.show_locked()
    assert not window.show_passwords_action.isChecked()
    assert not window.panel.reveal_timer.isActive()


def test_default_timeout_is_30_seconds() -> None:
    assert Settings().show_passwords_seconds == c.DEFAULT_SHOW_PASSWORDS_SECONDS == 30


# --- exclusion from screen capture -------------------------------------------------------


class FakeUser32:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def SetWindowDisplayAffinity(self, hwnd: int, affinity: int) -> int:  # noqa: N802
        self.calls.append((hwnd, affinity))
        return 1


def test_capture_exclusion_on_windows(qtbot: Any) -> None:
    dialog = QDialog()
    qtbot.addWidget(dialog)
    user32 = FakeUser32()
    assert qt_adapters.set_capture_excluded(dialog, True, platform="win32", user32=user32)
    assert qt_adapters.set_capture_excluded(dialog, False, platform="win32", user32=user32)
    hwnd = int(dialog.winId())
    assert user32.calls == [(hwnd, qt_adapters.WDA_EXCLUDEFROMCAPTURE),
                            (hwnd, qt_adapters.WDA_NONE)]


def test_capture_exclusion_is_a_no_op_elsewhere(qtbot: Any) -> None:
    dialog = QDialog()
    qtbot.addWidget(dialog)
    user32 = FakeUser32()
    assert not qt_adapters.set_capture_excluded(dialog, True, platform="linux", user32=user32)
    assert user32.calls == []


def test_guard_applies_capture_setting_to_every_window(qtbot: Any,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    applied: list[tuple[object, bool]] = []
    monkeypatch.setattr(qt_adapters, "set_capture_excluded",
                        lambda widget, excluded, **_k: applied.append((widget, excluded)) or True)
    guard = SessionGuard(Settings())
    assert Settings().exclude_from_capture is False
    dialog = QDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    assert all(widget is not dialog for widget, _ in applied)  # off by default: untouched

    guard.apply_settings(Settings(exclude_from_capture=True))
    assert (dialog, True) in applied  # windows already open
    later = QDialog()
    qtbot.addWidget(later)
    later.show()
    assert (later, True) in applied  # and windows opened afterwards

    guard.apply_settings(Settings(exclude_from_capture=False))
    assert (dialog, False) in applied and (later, False) in applied


# --- settings dialog ---------------------------------------------------------------------


def test_settings_dialog_edits_the_new_values(qtbot: Any) -> None:
    dialog = SettingsDialog(Settings(show_passwords_seconds=45, exclude_from_capture=True))
    qtbot.addWidget(dialog)
    assert dialog.values()["show_passwords_seconds"] == 45
    assert dialog.values()["exclude_from_capture"] is True
    dialog.restore_defaults()
    assert dialog.values()["show_passwords_seconds"] == 30
    assert dialog.values()["exclude_from_capture"] is False
