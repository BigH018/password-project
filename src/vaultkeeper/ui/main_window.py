"""Main window: menus, toolbar, backup banner, accounts panel, status bar.

Thin: account changes go through AccountService; lock / change-password / quit are signalled
to the controller.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import QAction, QLabel, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from vaultkeeper.config.constants import APP_NAME
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui.accounts_view import AccountsPanel
from vaultkeeper.ui.messages import confirm, error_text, show_error
from vaultkeeper.ui.theme import MUTED_STYLE, WARNING_BANNER_STYLE

BACKUP_BANNER = (
    "Opened from the backup copy. When you next save, the damaged vault file will be kept "
    "aside as a separate '.damaged' file and replaced. The backup copy itself is not touched."
)
COMING_IN_4C = "Coming in the next build (4c)"


class MainWindow(QMainWindow):
    """Top-level window. The controller handles locking, password changes and quitting."""

    lock_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    change_password_requested = pyqtSignal()

    def __init__(self, demo: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - DEMO (fake data)" if demo else APP_NAME)
        self.resize(1200, 720)
        self._accounts: AccountService | None = None
        self._vault_path = ""

        self.banner = QLabel(BACKUP_BANNER, self)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(WARNING_BANNER_STYLE)
        self.banner.hide()
        self.panel = AccountsPanel(self)
        self.locked_label = QLabel("Locked", self)
        self.locked_label.setAlignment(Qt.AlignCenter)
        self.locked_label.setStyleSheet(MUTED_STYLE)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.locked_label)
        self.stack.addWidget(self.panel)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._build_actions()
        self.panel.selection_changed.connect(self._update_actions)
        self.show_locked()

    def _build_actions(self) -> None:
        def action(text: str, shortcut: str | None = None) -> QAction:
            act = QAction(text, self)
            if shortcut:
                act.setShortcut(QKeySequence(shortcut))
            return act

        self.add_action = action("Add account", "Ctrl+N")
        self.edit_action = action("Edit")  # rows also open on double-click / Enter
        self.delete_action = action("Delete", "Delete")
        self.show_passwords_action = action("Show passwords")
        self.show_passwords_action.setCheckable(True)
        self.lock_action = action("&Lock", "Ctrl+L")
        self.change_password_action = action("Change master password...")
        self.manage_games_action = action("Manage games...")
        self.quit_action = action("&Quit", "Ctrl+Q")
        for pending in (self.add_action, self.edit_action, self.manage_games_action):
            pending.setToolTip(COMING_IN_4C)
            pending.setStatusTip(COMING_IN_4C)

        # Delete key only acts while the table has focus (never while typing in a field).
        self.delete_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.panel.table.addAction(self.delete_action)
        self.delete_action.triggered.connect(self._delete_selected)
        self.show_passwords_action.toggled.connect(self.panel.set_show_passwords)
        self.lock_action.triggered.connect(self.lock_requested)
        self.change_password_action.triggered.connect(self.change_password_requested)
        self.quit_action.triggered.connect(self.quit_requested)

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        for act in (self.add_action, self.edit_action, self.delete_action):
            toolbar.addAction(act)
        toolbar.addSeparator()
        toolbar.addAction(self.show_passwords_action)
        toolbar.addSeparator()
        toolbar.addAction(self.lock_action)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.change_password_action)
        file_menu.addAction(self.lock_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        games_menu = self.menuBar().addMenu("&Games")
        games_menu.addAction(self.manage_games_action)

    # --- states -----------------------------------------------------------------------------

    def show_locked(self) -> None:
        """Locked: drop every row, hide secrets, disable account actions."""
        self._accounts = None
        self.panel.clear()
        self.show_passwords_action.setChecked(False)
        self.banner.hide()
        self.stack.setCurrentWidget(self.locked_label)
        self._update_actions()
        self.statusBar().showMessage("Locked")

    def show_unlocked(self, vault_path: str, opened_from_backup: bool,
                      accounts: AccountService, games: GameService) -> None:
        """Unlocked: bind the services and show the accounts."""
        self._accounts = accounts
        self._vault_path = vault_path
        self.banner.setVisible(opened_from_backup)
        self.stack.setCurrentWidget(self.panel)
        self.panel.bind(accounts, games)
        self._update_actions()

    @property
    def unlocked(self) -> bool:
        """Whether account data is currently shown."""
        return self._accounts is not None

    def _update_actions(self) -> None:
        unlocked = self.unlocked
        for act in (self.lock_action, self.change_password_action, self.show_passwords_action):
            act.setEnabled(unlocked)
        self.delete_action.setEnabled(unlocked and self.panel.selected_account() is not None)
        for pending in (self.add_action, self.edit_action, self.manage_games_action):
            pending.setEnabled(False)  # enabled in 4c
        if unlocked:
            self.statusBar().showMessage(
                f"{self.panel.shown} of {self.panel.total} accounts  |  Vault: {self._vault_path}")

    # --- actions ----------------------------------------------------------------------------

    def _delete_selected(self) -> None:
        account = self.panel.selected_account()
        if account is None or self._accounts is None:
            return
        label = account.riot_id or account.login_username or account.email or "this account"
        if not confirm(self, "Delete account",
                       f"Delete {label}? This can't be undone.", ok_text="Delete"):
            return
        try:
            self._accounts.delete(account.id)
        except VaultKeeperError as exc:
            show_error(self, "Could not delete", error_text(exc))
            return
        self.banner.hide()  # a successful save ends the opened-from-backup state
        self.panel.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Closing the window quits the app (the controller locks first)."""
        self.quit_requested.emit()
        event.accept()
