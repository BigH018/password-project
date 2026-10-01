"""CR-L5: file pickers are Qt's own dialogs, so auto-lock sees activity and lock can close them.

A native Windows picker runs its own message loop: clicks in it never reach Qt's app-wide
event filter, and it isn't a QDialog that close_dialogs() can find.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication, QFileDialog

from vaultkeeper.ui import file_pickers
from vaultkeeper.ui.app_controller import AppController
from vaultkeeper.ui.qt_adapters import ActivityFilter


def _open_picker() -> QFileDialog | None:
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, QFileDialog) and widget.isVisible():
            return widget
    return None


@pytest.fixture
def chosen(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[QFileDialog]:
    """exec_() returns at once with a file selected, recording the dialog."""
    shown: list[QFileDialog] = []

    def fake_exec(self: QFileDialog) -> int:
        shown.append(self)
        self.selectFile(str(tmp_path / "picked.vault"))
        return 1

    monkeypatch.setattr(QFileDialog, "exec_", fake_exec)
    return shown


@pytest.mark.parametrize("pick", [
    lambda: file_pickers.choose_folder(None, "Choose a folder", ""),
    lambda: file_pickers.choose_save_file(None, "Save", ""),
    lambda: file_pickers.choose_open_file(None, "Open", ""),
])
def test_pickers_are_qt_dialogs(qapp: Any, chosen: list[QFileDialog], pick: Any) -> None:
    assert pick()  # returns the selected path
    assert chosen[0].testOption(QFileDialog.DontUseNativeDialog)


def test_save_picker_adds_the_vault_extension_filter(qapp: Any,
                                                     chosen: list[QFileDialog]) -> None:
    file_pickers.choose_save_file(None, "Save", "")
    assert ".vault" in chosen[0].nameFilters()[0]


def test_lock_closes_an_open_picker(qapp: Any) -> None:
    seen: list[bool] = []

    def lock_while_open() -> None:
        seen.append(_open_picker() is not None)
        AppController.close_dialogs(None)  # type: ignore[arg-type] - what lock() calls

    QTimer.singleShot(50, lock_while_open)
    assert file_pickers.choose_folder(None, "Choose a folder", "") == ""
    assert seen == [True] and _open_picker() is None


def test_typing_in_a_picker_counts_as_activity(qapp: Any) -> None:
    activity: list[bool] = []
    activity_filter = ActivityFilter(lambda: activity.append(True))
    qapp.installEventFilter(activity_filter)

    def type_then_close() -> None:
        picker = _open_picker()
        assert picker is not None
        QApplication.sendEvent(picker, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "a"))
        picker.reject()

    try:
        QTimer.singleShot(50, type_then_close)
        file_pickers.choose_open_file(None, "Open", "")
    finally:
        qapp.removeEventFilter(activity_filter)
    assert activity
