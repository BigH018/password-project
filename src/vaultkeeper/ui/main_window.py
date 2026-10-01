"""Main window: menus, toolbar, backup banner, accounts panel, status bar.

Thin: account changes go through AccountService; lock / change-password / quit are signalled
to the controller.
"""

from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import QAction, QLabel, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from vaultkeeper.config.constants import APP_NAME
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.entry_session import EntrySession
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.models import Game
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui.account_dialog import AccountDialog
from vaultkeeper.ui.accounts_view import AccountsPanel
from vaultkeeper.ui.copy_actions import CopyActions
from vaultkeeper.ui.game_setup_dialog import GameSetupDialog
from vaultkeeper.ui.generator_dialog import GeneratorDialog
from vaultkeeper.ui.messages import confirm, error_text, show_error
from vaultkeeper.ui.quick_add_dialog import QuickAddDialog
from vaultkeeper.ui.theme import MUTED_STYLE, WARNING_BANNER_STYLE

BACKUPS_OFF = ("Backups are off. <a href='setup'>Choose a backup folder</a> before entering "
               "real accounts.")
BACKUP_BANNER = (
    "Opened from the backup copy. When you next save, the damaged vault file will be kept "
    "aside as a separate '.damaged' file and replaced. The backup copy itself is not touched."
)


class MainWindow(QMainWindow):
    """Top-level window. The controller handles locking, password changes and quitting."""

    lock_requested = pyqtSignal()
    quit_requested = pyqtSignal()
    change_password_requested = pyqtSignal()
    minimized = pyqtSignal()
    backups_requested = pyqtSignal()
    backup_now_requested = pyqtSignal()
    export_requested = pyqtSignal()
    quick_add_opened = pyqtSignal()
    quick_add_closed = pyqtSignal()

    def __init__(self, demo: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - DEMO (fake data)" if demo else APP_NAME)
        self.resize(1200, 720)
        self._accounts: AccountService | None = None
        self._games: GameService | None = None
        self._vault_path = ""
        self.entry_session = EntrySession()

        self.banner = QLabel(BACKUP_BANNER, self)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(WARNING_BANNER_STYLE)
        self.banner.hide()
        self.backups_off = QLabel(BACKUPS_OFF, self)
        self.backups_off.setStyleSheet(WARNING_BANNER_STYLE)
        self.backups_off.linkActivated.connect(lambda _link: self.backups_requested.emit())
        self.backups_off.hide()
        self.panel = AccountsPanel(self)
        self.copy = CopyActions(self, self.panel, self._game_by_id)
        self.locked_label = QLabel("Locked", self)
        self.locked_label.setAlignment(Qt.AlignCenter)
        self.locked_label.setStyleSheet(MUTED_STYLE)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.locked_label)
        self.stack.addWidget(self.panel)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(self.backups_off)
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
        self.quick_add_action = action("Quick Add", "Ctrl+Shift+N")
        self.quick_add_action.setToolTip("Keyboard-first batch entry with paste assist")
        self.edit_action = action("Edit")  # rows also open on double-click / Enter
        self.delete_action = action("Delete", "Delete")
        self.show_passwords_action = action("Show passwords")
        self.show_passwords_action.setCheckable(True)
        self.lock_action = action("&Lock", "Ctrl+L")
        self.change_password_action = action("Change master password...")
        self.manage_games_action = action("Game setup...")
        self.quit_action = action("&Quit", "Ctrl+Q")
        self.generator_action = action("Generate password...", "Ctrl+G")
        self.backups_action = action("Backups...")
        self.backup_now_action = action("Backup now")
        self.export_action = action("Export encrypted copy...")
        self.generator_action.triggered.connect(self._open_generator)
        self.backups_action.triggered.connect(self.backups_requested)
        self.backup_now_action.triggered.connect(self.backup_now_requested)
        self.export_action.triggered.connect(self.export_requested)
        # Delete key only acts while the table has focus (never while typing in a field).
        self.delete_action.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.panel.table.addAction(self.delete_action)
        self.delete_action.triggered.connect(self._delete_selected)
        self.add_action.triggered.connect(self._add_account)
        self.quick_add_action.triggered.connect(self._quick_add)
        self.edit_action.triggered.connect(self._edit_selected)
        self.manage_games_action.triggered.connect(self._manage_games)
        self.panel.activated.connect(self._edit_selected)
        self.show_passwords_action.toggled.connect(self.panel.set_show_passwords)
        self.lock_action.triggered.connect(self.lock_requested)
        self.change_password_action.triggered.connect(self.change_password_requested)
        self.quit_action.triggered.connect(self.quit_requested)

        toolbar = self.addToolBar("Main")
        toolbar.setMovable(False)
        for act in (self.quick_add_action, self.add_action, self.edit_action,
                    self.delete_action):
            toolbar.addAction(act)
        toolbar.addSeparator()
        for act in self.copy.main_actions:
            toolbar.addAction(act)
        toolbar.addSeparator()
        toolbar.addAction(self.show_passwords_action)
        toolbar.addSeparator()
        toolbar.addAction(self.lock_action)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.change_password_action)
        file_menu.addAction(self.lock_action)
        file_menu.addSeparator()
        file_menu.addAction(self.backup_now_action)
        file_menu.addAction(self.backups_action)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)
        games_menu = self.menuBar().addMenu("&Games")
        games_menu.addAction(self.manage_games_action)
        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(self.generator_action)

    # --- states -----------------------------------------------------------------------------

    def show_locked(self) -> None:
        """Locked: drop every row, hide secrets, disable account actions."""
        self._accounts = self._games = None
        self.entry_session = EntrySession()  # batch state and counter don't survive a lock
        self.panel.clear()
        self.show_passwords_action.setChecked(False)
        self.banner.hide()
        self.backups_off.hide()
        self.stack.setCurrentWidget(self.locked_label)
        self._update_actions()
        self.statusBar().showMessage("Locked")

    def show_unlocked(self, vault_path: str, opened_from_backup: bool,
                      accounts: AccountService, games: GameService) -> None:
        """Unlocked: bind the services and show the accounts."""
        self._accounts, self._games = accounts, games
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
        for act in (self.lock_action, self.change_password_action, self.show_passwords_action,
                    self.add_action, self.quick_add_action, self.manage_games_action,
                    self.backups_action,
                    self.backup_now_action, self.export_action):
            act.setEnabled(unlocked)
        selected = unlocked and self.panel.selected_account() is not None
        self.delete_action.setEnabled(selected)
        self.edit_action.setEnabled(selected)
        self.copy.set_enabled(selected)
        if unlocked:
            self.statusBar().showMessage(
                f"{self.panel.shown} of {self.panel.total} accounts  |  Vault: {self._vault_path}")

    def set_backups_enabled(self, enabled: bool) -> None:
        """Show the "backups are off" banner while unlocked without a backup folder."""
        self.backups_off.setVisible(self.unlocked and not enabled)

    def context_extra_actions(self) -> list[QAction]:
        """Non-copy actions offered in the table's right-click menu."""
        return [self.edit_action, self.delete_action]

    def _game_by_id(self, game_id: str) -> Game | None:
        if self._games is None:
            return None
        return next((g for g in self._games.list_games() if g.id == game_id), None)

    def _open_generator(self) -> None:
        GeneratorDialog(copy=lambda pw: self.copy.copy_value(pw, "Password"),
                        parent=self).exec_()

    def changeEvent(self, event: QEvent) -> None:
        """Report minimizing (auto-lock on minimize)."""
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            self.minimized.emit()

    # --- actions ----------------------------------------------------------------------------

    def _after_save(self, account_id: str | None = None) -> None:
        self.banner.hide()  # a successful save ends the opened-from-backup state
        self.panel.refresh()
        if account_id is not None:
            self.panel.select_account(account_id)  # keep the edited/new row selected

    def _games_or_setup(self) -> list[Game]:
        """The games, opening Game setup first if there are none yet ([] if still none)."""
        if self._accounts is None or self._games is None:
            return []
        if not self._games.list_games():
            self.statusBar().showMessage(
                "Add a game first (for example Valorant), then add accounts to it.", 6000)
            self._manage_games()
        return self._games.list_games() if self._games else []

    def _add_account(self) -> None:
        games = self._games_or_setup()
        if not games or self._accounts is None:
            return
        dialog = AccountDialog(self._accounts, games,
                               default_game_id=self.panel.sidebar.current_game_id(), parent=self)
        if dialog.exec_() and dialog.saved is not None:
            self._after_save(dialog.saved.id)

    def _quick_add(self) -> None:
        games = self._games_or_setup()
        if not games or self._accounts is None:
            return
        dialog = QuickAddDialog(self._accounts, games, self.entry_session,
                                default_game_id=self.panel.sidebar.current_game_id(),
                                parent=self)
        dialog.saved_one.connect(lambda acc: self._after_save(acc.id))
        self.quick_add_opened.emit()  # longer auto-lock timeout while it's open
        try:
            dialog.exec_()
        finally:
            self.quick_add_closed.emit()

    def _edit_selected(self) -> None:
        account = self.panel.selected_account()
        if account is None or self._accounts is None or self._games is None:
            return
        dialog = AccountDialog(self._accounts, self._games.list_games(), account=account,
                               parent=self)
        if dialog.exec_() and dialog.saved is not None:
            self._after_save(dialog.saved.id)

    def _manage_games(self) -> None:
        if self._games is None:
            return
        dialog = GameSetupDialog(self._games, parent=self)
        dialog.exec_()
        if dialog.changed:
            self._after_save()

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
        self._after_save()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Closing the window quits the app (the controller locks first)."""
        self.quit_requested.emit()
        event.accept()
