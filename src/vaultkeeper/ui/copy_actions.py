"""Copy actions for the account table: toolbar/shortcuts and the right-click menu.

Everything goes through ``ClipboardGuard`` (auto-clear after N seconds, only if unchanged;
excluded from Windows clipboard history). Status messages name WHAT was copied, never the
value. Shortcuts follow KeePass: Ctrl+B username, Ctrl+C password, plus Ctrl+E email. They
only act while the table has focus, so Ctrl+C in a text field still copies text normally.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QObject, QPoint, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QAction, QMainWindow, QMenu

from vaultkeeper.core.game_template import FieldKind
from vaultkeeper.core.models import Account, Game
from vaultkeeper.security.clipboard import ClipboardGuard
from vaultkeeper.ui.accounts_view import AccountsPanel


class CopyActions(QObject):
    """Owns the copy QActions and builds the table's context menu."""

    def __init__(self, window: QMainWindow, panel: AccountsPanel,
                 game_lookup: Callable[[str], Game | None]) -> None:
        super().__init__(window)
        self._window = window
        self._panel = panel
        self._game = game_lookup
        self.clipboard: ClipboardGuard | None = None
        self.extra_menu_actions: list[QAction] = []

        self.copy_login = self._action("Copy username", "Ctrl+B",
                                       lambda a: a.login_username, "Username")
        self.copy_password = self._action("Copy password", "Ctrl+C",
                                          lambda a: a.password, "Password")
        self.copy_email = self._action("Copy email", "Ctrl+E", lambda a: a.email, "Email")
        self.copy_email_password = self._action(
            "Copy email password", None, lambda a: a.email_password or "", "Email password")
        self.copy_email_url = self._action(
            "Copy email login URL", None, lambda a: a.email_login_url or "", "Email login URL")
        panel.table.setContextMenuPolicy(Qt.CustomContextMenu)
        panel.table.customContextMenuRequested.connect(self._show_menu)

    @property
    def main_actions(self) -> list[QAction]:
        """Actions for the toolbar."""
        return [self.copy_login, self.copy_password, self.copy_email]

    def _action(self, text: str, shortcut: str | None, getter: Callable[[Account], str],
                what: str) -> QAction:
        action = QAction(text, self._window)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            self._panel.table.addAction(action)
        action.triggered.connect(lambda: self._copy_selected(getter, what))
        return action

    def set_enabled(self, enabled: bool) -> None:
        """Enable the copy actions only while an account is selected."""
        for action in (self.copy_login, self.copy_password, self.copy_email,
                       self.copy_email_password, self.copy_email_url):
            action.setEnabled(enabled)

    # --- copying ----------------------------------------------------------------------------

    def _copy_selected(self, getter: Callable[[Account], str], what: str) -> None:
        account = self._panel.selected_account()
        if account is not None:
            self.copy_value(getter(account), what)

    def copy_value(self, value: str, what: str) -> None:
        """Copy ``value`` with auto-clear and report it in the status bar (never the value)."""
        bar = self._window.statusBar()
        if self.clipboard is None:
            return
        if not value:
            bar.showMessage(f"No {what.lower()} saved for this account.", 4000)
            return
        self.clipboard.copy(value)
        seconds = int(self.clipboard.clear_after)
        bar.showMessage(f"{what} copied. The clipboard clears in {seconds} s.", seconds * 1000)

    # --- context menu -----------------------------------------------------------------------

    def build_menu(self, account: Account, extra: list[QAction]) -> QMenu:
        """Right-click menu for ``account``: copy items (plus secret extra fields), then extra."""
        menu = QMenu(self._window)
        menu.addAction(self.copy_login)
        menu.addAction(self.copy_password)
        menu.addAction(self.copy_email)
        if account.email_password:
            menu.addAction(self.copy_email_password)
        if account.email_login_url:
            menu.addAction(self.copy_email_url)
        self.extra_menu_actions = []
        game = self._game(account.game_id)
        if game is not None:
            for custom in game.template.custom_fields:
                value = account.extra_value(custom.id)
                if custom.kind is FieldKind.SECRET and value:
                    act = menu.addAction(f"Copy {custom.label}")
                    act.triggered.connect(
                        lambda _c=False, v=value, w=custom.label: self.copy_value(v, w))
                    self.extra_menu_actions.append(act)
        if extra:
            menu.addSeparator()
            for action in extra:
                menu.addAction(action)
        return menu

    def _show_menu(self, pos: QPoint) -> None:
        index = self._panel.table.indexAt(pos)
        if not index.isValid():
            return
        self._panel.table.selectRow(index.row())
        account = self._panel.selected_account()
        if account is None:
            return
        extra = getattr(self._window, "context_extra_actions", lambda: [])()
        menu = self.build_menu(account, extra)
        try:
            menu.exec_(self._panel.table.viewport().mapToGlobal(pos))
        finally:  # the menu's "Copy <secret field>" actions hold the secret values
            self.extra_menu_actions = []
            menu.deleteLater()
