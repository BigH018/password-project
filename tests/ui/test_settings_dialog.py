"""Settings dialog: values, defaults, Backups button, and the controller saving + applying."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtCore import Qt

from test_clipboard import FakeClipboard
from vaultkeeper.config.settings import Settings, load_settings
from vaultkeeper.ui import app_controller
from vaultkeeper.ui.main_window import MainWindow
from vaultkeeper.ui.qt_adapters import QtTaskRunner
from vaultkeeper.ui.session_guard import SessionGuard
from vaultkeeper.ui.settings_dialog import EDITED_FIELDS, SettingsDialog

CUSTOM = Settings(autolock_minutes=9, quick_add_autolock_minutes=30, clipboard_clear_seconds=40,
                  lock_on_minimize=False, lock_on_session_lock=False)


def _dialog(qtbot: Any, settings: Settings = CUSTOM, **kwargs: Any) -> SettingsDialog:
    dialog = SettingsDialog(settings, **kwargs)
    qtbot.addWidget(dialog)
    return dialog


def test_shows_current_values(qtbot: Any) -> None:
    values = _dialog(qtbot).values()
    assert set(values) == set(EDITED_FIELDS)
    assert values == {name: getattr(CUSTOM, name) for name in EDITED_FIELDS}


def test_restore_defaults(qtbot: Any) -> None:
    dialog = _dialog(qtbot)
    dialog.restore_defaults()
    defaults = Settings()
    assert dialog.values() == {name: getattr(defaults, name) for name in EDITED_FIELDS}


def test_spin_boxes_cannot_leave_allowed_ranges(qtbot: Any) -> None:
    dialog = _dialog(qtbot)
    dialog.autolock_spin.setValue(0)
    dialog.clipboard_spin.setValue(10_000)
    assert dialog.values()["autolock_minutes"] == 1
    assert dialog.values()["clipboard_clear_seconds"] == 300


def test_backups_button(qtbot: Any) -> None:
    assert not _dialog(qtbot).backups_button.isEnabled()
    opened: list[bool] = []
    dialog = _dialog(qtbot, open_backups=lambda: opened.append(True))
    dialog.backups_button.click()
    assert opened == [True]


def test_settings_in_file_menu(qtbot: Any) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    file_menu = window.menuBar().actions()[0].menu()
    assert window.settings_action in file_menu.actions()
    assert window.settings_action.shortcut().toString() == "Ctrl+,"
    fired: list[bool] = []
    window.settings_requested.connect(lambda: fired.append(True))
    window.settings_action.trigger()
    assert fired == [True]


# --- controller ------------------------------------------------------------------------------


def _controller(qtbot: Any, settings_file: Path, monkeypatch: Any, accept: bool,
                chosen: dict[str, Any]) -> app_controller.AppController:
    class FakeDialog:
        def __init__(self, _settings: Settings, _open_backups: Any, parent: Any) -> None:
            pass

        def deleteLater(self) -> None:  # noqa: N802 - Qt API (run_modal)
            pass

        def exec_(self) -> int:
            return int(accept)

        def values(self) -> dict[str, Any]:
            return chosen

    monkeypatch.setattr(app_controller, "SettingsDialog", FakeDialog)
    guard = SessionGuard(Settings(vault_path="C:/fake/a.vault"), backend=FakeClipboard())
    ctrl = app_controller.AppController(
        Settings(vault_path="C:/fake/a.vault"), settings_file, QtTaskRunner(),
        lambda p: None,  # type: ignore[arg-type, return-value]
        guard=guard,
    )
    qtbot.addWidget(ctrl.window)
    return ctrl


@pytest.fixture
def chosen() -> dict[str, Any]:
    return {name: getattr(CUSTOM, name) for name in EDITED_FIELDS}


def test_save_applies_and_persists(qtbot: Any, tmp_path: Path, monkeypatch: Any,
                                   chosen: dict[str, Any]) -> None:
    file = tmp_path / "settings.json"
    ctrl = _controller(qtbot, file, monkeypatch, True, chosen)
    ctrl._open_settings()
    saved = load_settings(file)
    assert saved.autolock_minutes == 9 and saved.lock_on_session_lock is False
    assert saved.vault_path == "C:/fake/a.vault"  # untouched fields kept
    assert ctrl.guard.clipboard.clear_after == 40
    assert ctrl.guard.tracker.timeout == 9 * 60
    assert "Settings saved" in ctrl.window.statusBar().currentMessage()


def test_cancel_changes_nothing(qtbot: Any, tmp_path: Path, monkeypatch: Any,
                                chosen: dict[str, Any]) -> None:
    file = tmp_path / "settings.json"
    ctrl = _controller(qtbot, file, monkeypatch, False, chosen)
    ctrl._open_settings()
    assert not file.exists()
    assert ctrl.guard.tracker.timeout == Settings().autolock_minutes * 60


def test_unsavable_settings_still_apply_and_say_so(qtbot: Any, tmp_path: Path,
                                                   monkeypatch: Any,
                                                   chosen: dict[str, Any]) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    ctrl = _controller(qtbot, blocker / "settings.json", monkeypatch, True, chosen)
    ctrl._open_settings()
    assert ctrl.guard.tracker.timeout == 9 * 60
    assert "could not be saved" in ctrl.window.statusBar().currentMessage()


def test_session_lock_setting_applies_live(qapp: Any) -> None:
    guard = SessionGuard(Settings(lock_on_session_lock=True), backend=FakeClipboard())
    seen: list[str] = []
    guard.lock_needed.connect(seen.append)
    guard.arm()
    guard._session_locked()
    guard.apply_settings(Settings(lock_on_session_lock=False))
    guard._session_locked()
    assert seen == ["session"]


def test_guard_shutdown_stops_timer_and_activity_filter(qapp: Any) -> None:
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QKeyEvent
    from PyQt5.QtWidgets import QWidget

    guard = SessionGuard(Settings(), backend=FakeClipboard())
    seen: list[bool] = []
    guard._filter._on_activity = lambda: seen.append(True)
    target = QWidget()
    qapp.sendEvent(target, QKeyEvent(QEvent.KeyPress, 0x41, Qt.NoModifier))
    assert seen == [True]
    guard.shutdown()
    qapp.sendEvent(target, QKeyEvent(QEvent.KeyPress, 0x41, Qt.NoModifier))
    assert seen == [True] and not guard._timer.isActive()
