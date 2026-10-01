"""Screen flow: Welcome -> Create/Unlock -> Main window, and Lock -> Unlock.

UI wiring only. All decisions about vault state live in ``VaultService``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from PyQt5.QtCore import QObject, QStandardPaths, QTimer
from PyQt5.QtWidgets import QApplication, QDialog

from vaultkeeper.config.constants import VAULT_EXTENSION
from vaultkeeper.config.settings import Settings, save_settings, update_settings
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.backup import BackupService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.serialization import dumps_payload
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import VaultIOError, VaultKeeperError
from vaultkeeper.ui.backup_dialog import BackupDialog
from vaultkeeper.ui.change_password_dialog import ChangePasswordDialog
from vaultkeeper.ui.create_vault_dialog import CreateVaultDialog
from vaultkeeper.ui.export_dialog import ExportDialog
from vaultkeeper.ui.main_window import MainWindow
from vaultkeeper.ui.messages import error_text
from vaultkeeper.ui.qt_adapters import QtTaskRunner
from vaultkeeper.ui.session_guard import SessionGuard
from vaultkeeper.ui.unlock_dialog import UnlockDialog
from vaultkeeper.ui.welcome_dialog import WelcomeDialog

log = logging.getLogger(__name__)


def default_vault_path() -> Path:
    """Suggested location for a new vault: Documents/VaultKeeper/vaultkeeper.vault."""
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
    return Path(docs) / "VaultKeeper" / f"vaultkeeper{VAULT_EXTENSION}"


class AppController(QObject):
    """Owns the main window and the current VaultService; drives dialogs."""

    def __init__(
        self,
        settings: Settings,
        settings_file: Path,
        runner: QtTaskRunner,
        service_factory: Callable[[Path], VaultService],
        demo: bool = False,
        new_vault_dir: Path | None = None,
        guard: SessionGuard | None = None,
    ) -> None:
        super().__init__()
        self._new_vault_dir = new_vault_dir
        self.guard = guard or SessionGuard(settings)
        self.backups: BackupService | None = None
        self._settings = settings
        self._settings_file = settings_file
        self._runner = runner
        self._factory = service_factory
        self.service: VaultService | None = None
        self.window = MainWindow(demo=demo)
        self.window.lock_requested.connect(self.lock)
        self.window.quit_requested.connect(self.quit)
        self.window.change_password_requested.connect(self._change_password)
        self.window.copy.clipboard = self.guard.clipboard
        self.window.minimized.connect(self.guard.window_minimized)
        self.window.backups_requested.connect(self._backup_settings)
        self.window.backup_now_requested.connect(self._backup_now)
        self.window.export_requested.connect(self._export)
        self.guard.lock_needed.connect(self._auto_lock)

    # --- flow -------------------------------------------------------------------------------

    def start(self) -> None:
        """Entry point once the Qt event loop is running."""
        self.window.show()
        self.guard.watch_session(int(self.window.winId()))
        path = Path(self._settings.vault_path) if self._settings.vault_path else None
        if path is not None and path.is_file():
            self.service = self._factory(path)
            self._unlock()
        else:
            self._welcome()

    def _welcome(self) -> None:
        dialog = WelcomeDialog(parent=self.window)
        if not dialog.exec_() or dialog.choice is None:
            self.quit()
            return
        if dialog.choice == "create":
            self._create()
        elif dialog.path is not None:
            self.service = self._factory(dialog.path)
            self._unlock()

    def _create(self) -> None:
        suggested = (
            self._new_vault_dir / f"new{VAULT_EXTENSION}"
            if self._new_vault_dir is not None
            else default_vault_path()
        )
        dialog = CreateVaultDialog(
            self._factory, self._runner.cancel_pending, suggested, parent=self.window
        )
        if dialog.exec_() and dialog.service is not None:
            self.service = dialog.service
            self._remember_vault(self.service.path)
            self._show_unlocked()
        else:
            self._welcome()

    def _unlock(self) -> None:
        if self.service is None:
            self._welcome()
            return
        dialog = UnlockDialog(self.service, self._runner.cancel_pending, parent=self.window)
        if dialog.exec_():
            self._remember_vault(self.service.path)
            self._show_unlocked()
        elif dialog.other_vault_path is not None:
            self.service = self._factory(dialog.other_vault_path)
            self._unlock()
        else:
            self.quit()

    def _show_unlocked(self) -> None:
        if self.service is None:
            return
        self.window.show_unlocked(
            str(self.service.path),
            self.service.opened_from_backup,
            AccountService(self.service),
            GameService(self.service),
        )
        self._start_backups(self.service)
        self.guard.arm()

    # --- backups & export -------------------------------------------------------------------

    def _start_backups(self, service: VaultService) -> None:
        s = self._settings
        folder = Path(s.backup_dir) if s.backup_dir else None
        self.backups = BackupService(service.path, folder, s.backup_keep,
                                     s.backup_min_interval_minutes)
        if self._after_save_backup not in service.on_saved:
            service.on_saved.append(self._after_save_backup)
        self.window.set_backups_enabled(self.backups.enabled)

    def _run_backup(self, step: Callable[[], Path | None]) -> None:
        try:
            if step() is not None:
                self.window.statusBar().showMessage("Backup saved.", 4000)
        except VaultKeeperError as exc:
            self.window.statusBar().showMessage(f"Backup failed: {error_text(exc)}", 10000)

    def _after_save_backup(self) -> None:
        if self.backups is not None:
            self._run_backup(self.backups.after_save)

    def _backup_now(self) -> None:
        if self.backups is not None:
            self._run_backup(self.backups.backup_now)

    def _backup_settings(self) -> None:
        if self.backups is None:
            return
        dialog = BackupDialog(self.backups, parent=self.window)
        if dialog.exec_():
            folder = self.backups.backup_dir
            self._settings = update_settings(
                self._settings, backup_dir=str(folder) if folder else None,
                backup_keep=self.backups.keep,
                backup_min_interval_minutes=self.backups.min_interval_minutes)
            self._save_settings()
        self.window.set_backups_enabled(self.backups.enabled)

    def _export(self) -> None:
        if self.service is None or not self.service.is_unlocked:
            return
        base = self._new_vault_dir or default_vault_path().parent
        stamp = time.strftime("%Y%m%d")
        default = base / f"VaultKeeper-export-{stamp}{VAULT_EXTENSION}"
        dialog = ExportDialog(dumps_payload(self.service.data), self.service.path,
                              self._runner, self._runner.cancel_pending, default,
                              parent=self.window)
        if dialog.exec_() and dialog.written_path is not None:
            self.window.statusBar().showMessage("Encrypted export saved.", 6000)

    # --- actions ----------------------------------------------------------------------------

    def _change_password(self) -> None:
        if self.service is None or not self.service.is_unlocked:
            return
        dialog = ChangePasswordDialog(self.service, self._runner.cancel_pending, self.window)
        if dialog.exec_():
            self.window.banner.setVisible(self.service.opened_from_backup)
            self.window.statusBar().showMessage("Master password changed.", 5000)

    def close_dialogs(self) -> None:
        """Close every open dialog (drafts are discarded: locking beats convenience)."""
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                # force_close skips "discard changes?" prompts: locking always wins.
                getattr(widget, "force_close", widget.reject)()

    def _auto_lock(self, reason: str) -> None:
        log.info("Auto-lock (%s)", reason)
        self.lock()

    def lock(self) -> None:
        """Close dialogs, drop decrypted state, clear the window, ask for the password again."""
        self.close_dialogs()
        self._runner.cancel_pending()
        self.guard.disarm()  # stops auto-lock and clears our clipboard copy
        if self.backups is not None:
            self._run_backup(self.backups.on_lock_or_exit)
        if self.service is not None:
            self.service.lock()
        self.window.show_locked()
        if self.service is not None:
            # Deferred so any dialog event loops we just closed can unwind first.
            QTimer.singleShot(0, self._unlock)

    def quit(self) -> None:
        """Lock (wiping keys) and leave the event loop. Running work is abandoned."""
        self._runner.cancel_pending()
        self.guard.disarm()
        if self.backups is not None:
            self._run_backup(self.backups.on_lock_or_exit)
        if self.service is not None:
            self.service.lock()
        QApplication.quit()

    def _remember_vault(self, path: Path) -> None:
        if self._settings.vault_path == str(path):
            return
        self._settings = update_settings(self._settings, vault_path=str(path))
        self._save_settings()

    def _save_settings(self) -> None:
        try:
            save_settings(self._settings_file, self._settings)
        except VaultIOError:
            log.warning("Could not save settings")
