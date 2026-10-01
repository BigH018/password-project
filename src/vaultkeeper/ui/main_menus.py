"""Toolbar and menu bar for the main window (layout only: the actions live on the window)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vaultkeeper.ui.main_window import MainWindow


def install_toolbar_and_menus(window: MainWindow) -> None:
    """Add the toolbar and the File / Games / Tools menus built from the window's actions."""
    toolbar = window.addToolBar("Main")
    toolbar.setMovable(False)
    for act in (window.quick_add_action, window.add_action, window.edit_action,
                window.delete_action):
        toolbar.addAction(act)
    toolbar.addSeparator()
    for act in window.copy.main_actions:
        toolbar.addAction(act)
    toolbar.addSeparator()
    toolbar.addAction(window.show_passwords_action)
    toolbar.addSeparator()
    toolbar.addAction(window.lock_action)

    file_menu = window.menuBar().addMenu("&File")
    file_menu.addAction(window.change_password_action)
    file_menu.addAction(window.lock_action)
    file_menu.addSeparator()
    file_menu.addAction(window.backup_now_action)
    file_menu.addAction(window.backups_action)
    file_menu.addAction(window.export_action)
    file_menu.addSeparator()
    file_menu.addAction(window.settings_action)
    file_menu.addSeparator()
    file_menu.addAction(window.quit_action)
    games_menu = window.menuBar().addMenu("&Games")
    games_menu.addAction(window.manage_games_action)
    tools_menu = window.menuBar().addMenu("&Tools")
    tools_menu.addAction(window.generator_action)
