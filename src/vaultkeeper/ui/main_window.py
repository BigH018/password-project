"""Main window: menus, toolbar, backup banner, accounts panel, status bar.

Thin: account changes go through AccountService; lock / change-password / quit are signalled
to the controller.
"""

from __future__ import annotations

from PyQt5.QtCore import QByteArray, QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import QAction, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from vaultkeeper.config.constants import WINDOW_TITLE
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.entry_session import EntrySession
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.models import Game
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui.account_dialog import AccountDialog
from vaultkeeper.ui.accounts_view import AccountsPanel
from vaultkeeper.ui.copy_actions import CopyActions
from vaultkeeper.ui.email_generator_dialog import EmailGeneratorLauncher
from vaultkeeper.ui.game_setup_dialog import GameSetupDialog
from vaultkeeper.ui.generator_dialog import GeneratorDialog
from vaultkeeper.ui.main_menus import install_toolbar_and_menus
from vaultkeeper.ui.messages import confirm, error_text, local_time_text, run_modal, show_error
from vaultkeeper.ui.quick_add_dialog import QuickAddDialog
from vaultkeeper.ui.safe_text import link_label, plain_label
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
    settings_requested = pyqtSignal()
    quick_add_opened = pyqtSignal()
    quick_add_closed = pyqtSignal()

    def __init__(self, demo: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{WINDOW_TITLE} - DEMO (fake data)" if demo else WINDOW_TITLE)
        self.resize(1200, 720)
        self._accounts: AccountService | None = None
        self._games: GameService | None = None
        self._vault_path = ""
        self.entry_session = EntrySession()

        self.banner = plain_label(BACKUP_BANNER, self)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(WARNING_BANNER_STYLE)
        self.banner.hide()
        self.backups_off = link_label(BACKUPS_OFF, self)
        self.backups_off.setStyleSheet(WARNING_BANNER_STYLE)
        self.backups_off.linkActivated.connect(lambda _link: self.backups_requested.emit())
        self.backups_off.hide()
        self.backup_failed = plain_label(parent=self)
        self.backup_failed.setWordWrap(True)
        self.backup_failed.setStyleSheet(WARNING_BANNER_STYLE)
        self.backup_failed.hide()
        self.panel = AccountsPanel(self)
        self.copy = CopyActions(self, self.panel, self._game_by_id)
        self.email_tools = EmailGeneratorLauncher(
            self._addresses_in_use, lambda email: self.copy.copy_value(email, "Email"))
        self.locked_label = plain_label("Locked", self)
        self.locked_label.setAlignment(Qt.AlignCenter)
        self.locked_label.setStyleSheet(MUTED_STYLE)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.locked_label)
        self.stack.addWidget(self.panel)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(self.backups_off)
        layout.addWidget(self.backup_failed)
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
        self.email_generator_action = action("Generate email...", "Ctrl+Shift+G")
        self.backups_action = action("Backups...")
        self.backup_now_action = action("Backup now")
        self.export_action = action("Export encrypted copy...")
        self.settings_action = action("&Settings...", "Ctrl+,")
        self.generator_action.triggered.connect(self._open_generator)
        self.email_generator_action.triggered.connect(self._open_email_generator)
        self.backups_action.triggered.connect(self.backups_requested)
        self.backup_now_action.triggered.connect(self.backup_now_requested)
        self.export_action.triggered.connect(self.export_requested)
        self.settings_action.triggered.connect(self.settings_requested)
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
        self.panel.reveal_expired.connect(lambda: self.show_passwords_action.setChecked(False))
        self.lock_action.triggered.connect(self.lock_requested)
        self.change_password_action.triggered.connect(self.change_password_requested)
        self.quit_action.triggered.connect(self.quit_requested)

        install_toolbar_and_menus(self)

    # --- states -----------------------------------------------------------------------------

    def show_locked(self) -> None:
        """Locked: drop every row, hide secrets, disable account actions."""
        self._accounts = self._games = None
        self.entry_session = EntrySession()  # batch state and counter don't survive a lock
        self.panel.clear()
        self.show_passwords_action.setChecked(False)
        self.banner.hide()
        self.backups_off.hide()
        self.backup_failed.hide()
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

    def geometry_text(self) -> str:
        """Size, position and maximized state as base64 (for the settings file)."""
        return bytes(self.saveGeometry().toBase64()).decode("ascii")

    def restore_geometry_text(self, text: str | None) -> bool:
        """Restore ``geometry_text`` output. Qt moves it back on screen if a monitor is gone."""
        if not text:
            return False
        return self.restoreGeometry(QByteArray.fromBase64(text.encode("ascii")))

    @property
    def unlocked(self) -> bool:
        """Whether account data is currently shown."""
        return self._accounts is not None

    def _update_actions(self) -> None:
        unlocked = self.unlocked
        for act in (self.lock_action, self.change_password_action, self.show_passwords_action,
                    self.add_action, self.quick_add_action, self.manage_games_action,
                    self.backups_action, self.email_generator_action,
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

    def set_backup_failure(self, failed_at: str | None) -> None:
        """Show "last backup failed" (UTC ISO time) until a backup succeeds; None hides it."""
        if failed_at is not None:
            self.backup_failed.setText(f"Last backup failed at {local_time_text(failed_at)}. "
                                       "Check the backup folder (File -> Backups...).")
        self.backup_failed.setVisible(self.unlocked and failed_at is not None)

    def context_extra_actions(self) -> list[QAction]:
        """Non-copy actions offered in the table's right-click menu."""
        return [self.edit_action, self.delete_action]

    def _game_by_id(self, game_id: str) -> Game | None:
        if self._games is None:
            return None
        return next((g for g in self._games.list_games() if g.id == game_id), None)

    def _open_generator(self) -> None:
        run_modal(GeneratorDialog(copy=lambda pw: self.copy.copy_value(pw, "Password"),
                                  parent=self))

    def _addresses_in_use(self) -> frozenset[str]:
        return self._accounts.addresses_in_use() if self._accounts else frozenset()

    def _open_email_generator(self) -> None:
        game = self._game_by_id(self.panel.sidebar.current_game_id() or "")
        self.email_tools.open(game.name if game else "", parent=self)

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
                               default_game_id=self.panel.sidebar.current_game_id(), parent=self,
                               pick_email=self.email_tools.pick)
        if run_modal(dialog) and dialog.saved is not None:
            self._after_save(dialog.saved.id)

    def _quick_add(self) -> None:
        games = self._games_or_setup()
        if not games or self._accounts is None:
            return
        dialog = QuickAddDialog(self._accounts, games, self.entry_session,
                                default_game_id=self.panel.sidebar.current_game_id(),
                                parent=self, pick_email=self.email_tools.pick)
        dialog.saved_one.connect(lambda acc: self._after_save(acc.id))
        self.quick_add_opened.emit()  # longer auto-lock timeout while it's open
        try:
            run_modal(dialog)
        finally:
            self.quick_add_closed.emit()

    def _edit_selected(self) -> None:
        account = self.panel.selected_account()
        if account is None or self._accounts is None or self._games is None:
            return
        dialog = AccountDialog(self._accounts, self._games.list_games(), account=account,
                               parent=self, pick_email=self.email_tools.pick)
        if run_modal(dialog) and dialog.saved is not None:
            self._after_save(dialog.saved.id)

    def _manage_games(self) -> None:
        if self._games is None:
            return
        dialog = GameSetupDialog(self._games, parent=self)
        run_modal(dialog)
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
