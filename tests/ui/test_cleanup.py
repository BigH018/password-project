"""Menus, message boxes and dialogs are deleted after use (CR-M4).

Otherwise they live on as hidden children of the main window, some holding secret values
(a password field, a "Copy <secret field>" action), long after the vault is locked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt5 import sip
from PyQt5.QtCore import QCoreApplication, QEvent
from PyQt5.QtWidgets import QDialog, QMenu, QMessageBox

from conftest import FAST_KDF
from vaultkeeper import demo
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui import main_window as mw
from vaultkeeper.ui.messages import confirm as real_confirm  # bound before the autouse stub
from vaultkeeper.ui.messages import show_error as real_show_error


def _flush_deletes() -> None:
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def window(qtbot: Any, tmp_path: Path) -> mw.MainWindow:
    env = demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock(demo.DEMO_PASSWORD)
    win = mw.MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.show_unlocked(str(svc.path), False, AccountService(svc), GameService(svc))
    return win


@pytest.fixture
def no_modal_loops(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """exec_() returns at once (as if closed) and records what was shown."""
    shown: list[Any] = []

    def fake_exec(self: Any, *_a: Any) -> int:
        shown.append(self)
        return 0

    for cls in (QDialog, QMenu, QMessageBox):
        monkeypatch.setattr(cls, "exec_", fake_exec)
    return shown


def test_context_menu_is_deleted_after_use(window: mw.MainWindow,
                                           no_modal_loops: list[Any]) -> None:
    table = window.panel.table
    pos = table.visualRect(table.model().index(0, 0)).center()
    window.copy._show_menu(pos)
    menu = no_modal_loops[0]
    assert isinstance(menu, QMenu)
    assert window.copy.extra_menu_actions == []  # no "Copy <secret>" actions kept around
    _flush_deletes()
    assert sip.isdeleted(menu)


def test_message_boxes_are_deleted_after_use(window: mw.MainWindow,
                                             no_modal_loops: list[Any]) -> None:
    real_confirm(window, "Delete account", "Delete FakePlayer1#TEST?")
    real_show_error(window, "Could not delete", "Fake problem")
    assert len(no_modal_loops) == 2
    _flush_deletes()
    assert all(sip.isdeleted(box) for box in no_modal_loops)


def test_dialogs_opened_from_the_window_are_deleted(window: mw.MainWindow,
                                                    no_modal_loops: list[Any]) -> None:
    window.panel.table.selectRow(0)
    window.edit_action.trigger()
    window.add_action.trigger()
    window.quick_add_action.trigger()
    window.manage_games_action.trigger()
    window._open_generator()
    assert len(no_modal_loops) == 5
    _flush_deletes()
    assert window.findChildren(QDialog) == []
