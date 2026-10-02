"""Screen flow: Welcome -> Create/Unlock -> Main window, and Lock -> Unlock.

UI wiring only. All decisions about vault state live in ``VaultService``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PyQt5.QtCore import QObject, QStandardPaths, Qt, QTimer
from PyQt5.QtWidgets import QApplication, QDialog

from vaultkeeper.config.constants import VAULT_EXTENSION
from vaultkeeper.config.settings import Settings, SettingsFile
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.backup import BackupJob, BackupService, run_backup_job
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.serialization import dumps_payload
from vaultkeeper.core.tasks import TaskRunner
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui import messages
from vaultkeeper.ui.backup_dialog import BackupDialog, after_password_change
from vaultkeeper.ui.change_password_dialog import ChangePasswordDialog
from vaultkeeper.ui.create_vault_dialog import CreateVaultDialog
from vaultkeeper.ui.export_dialog import ExportDialog
from vaultkeeper.ui.main_window import MainWindow
from vaultkeeper.ui.messages import error_text, run_modal
from vaultkeeper.ui.qt_adapters import QtTaskRunner, VaultInstanceLock
from vaultkeeper.ui.session_guard import SessionGuard
from vaultkeeper.ui.settings_dialog import SettingsDialog
from vaultkeeper.ui.unlock_dialog import UnlockDialog, check_last_saved, record_last_saved
from vaultkeeper.ui.welcome_dialog import WelcomeDialog

log = logging.getLogger(__name__)
QUIT_BACKUP_WAIT_SECONDS = 15  # a running backup gets this long to finish at quit


def default_vault_path() -> Path:
    """Suggested location for a new vault: Documents/VaultKeeper/vaultkeeper.vault."""
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or str(Path.home())
    return Path(docs) / "VaultKeeper" / f"vaultkeeper{VAULT_EXTENSION}"


ALREADY_OPEN = ("This vault is already open in another Account Manager window. Use that "
                "window, or close it first and then open the vault here.")


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
        backup_runner: TaskRunner | None = None,
    ) -> None:
        super().__init__()
        self._new_vault_dir = new_vault_dir
        self.guard = guard or SessionGuard(settings)
        self.backups: BackupService | None = None
        # Backups run on their own runner (CR-L6): lock cancels self._runner's work, but a
        # backup in flight only handles encrypted bytes and its result must be recorded.
        self._backup_runner: TaskRunner = backup_runner or QtTaskRunner()
        self._backup_busy = False
        self._backup_next: Callable[[], BackupJob | None] | None = None  # asked while busy
        self._backup_idle = threading.Event()
        self._backup_idle.set()
        self.settings = SettingsFile(settings_file, settings)
        self._runner = runner
        self._factory = service_factory
        self.service: VaultService | None = None
        self._unlock_minimized = False
        self._instance_lock = VaultInstanceLock()  # one running copy per vault (SEC-M2)
        self._reported_damaged: Path | None = None
        self.window = MainWindow(demo=demo)
        self.window.restore_geometry_text(settings.window_geometry)  # shown after unlock
        self.window.email_tools.domain = settings.email_domain
        self.window.lock_requested.connect(self.lock)
        self.window.quit_requested.connect(self.quit)
        self.window.change_password_requested.connect(self._change_password)
        self.window.copy.clipboard = self.guard.clipboard
        self.window.minimized.connect(self.guard.window_minimized)
        self.window.backups_requested.connect(self._backup_settings)
        self.window.backup_now_requested.connect(self._backup_now)
        self.window.export_requested.connect(self._export)
        self.window.settings_requested.connect(self._open_settings)
        self.guard.lock_needed.connect(self._auto_lock)
        self.window.quick_add_opened.connect(self._quick_add_opened)
        self.window.quick_add_closed.connect(self.guard.tracker.pop_override)

    # --- flow -------------------------------------------------------------------------------

    def start(self) -> None:
        """Entry point once the Qt event loop is running.

        The main window stays hidden until a vault is open: before that only the small
        welcome/create/unlock dialogs show, each with its own taskbar button (no parent).
        """
        self.guard.watch_session(int(self.window.winId()))  # native handle; window stays hidden
        vault_path = self.settings.current.vault_path
        path = Path(vault_path) if vault_path else None
        if path is not None and path.is_file():
            self.service = self._factory(path)
            self._unlock()
        else:
            self._welcome()

    def _welcome(self) -> None:
        dialog = WelcomeDialog(parent=None)
        if not run_modal(dialog) or dialog.choice is None:
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
            self._factory, self._runner.cancel_pending, suggested, parent=None
        )
        if run_modal(dialog) and dialog.service is not None:
            self.service = dialog.service
            self._instance_lock.acquire(self.service.path)
            self._remember_vault(self.service.path)
            self._show_unlocked()
        else:
            self._welcome()

    def _unlock(self) -> None:
        if self.service is None:
            self._welcome()
            return
        if not self._instance_lock.acquire(self.service.path):  # before asking the password
            messages.show_error(None, "Vault already open", ALREADY_OPEN)
            self.service = None
            self._welcome()
            return
        dialog = UnlockDialog(self.service, self._runner.cancel_pending, parent=None)
        if self._unlock_minimized:  # locked by minimizing: wait on the taskbar, don't pop up
            self._unlock_minimized = False
            dialog.setWindowState(Qt.WindowMinimized)
        if run_modal(dialog):
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
        self._present_window()
        self._start_backups(self.service)
        self.window.panel.set_reveal_seconds(self.settings.current.show_passwords_seconds)
        note = check_last_saved(self.window, self.settings, self.service)
        self.window.statusBar().showMessage(note, 10000)
        self.guard.arm()

    def _present_window(self) -> None:
        """Show the main window (restored if it was minimized) and bring it to the front."""
        if self.window.isMinimized():
            self.window.showNormal()
        else:
            self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    # --- backups & export -------------------------------------------------------------------

    def _start_backups(self, service: VaultService) -> None:
        s = self.settings.current
        folder = Path(s.backup_dir) if s.backup_dir else None
        if self.backups is None or self.backups.vault_path != service.path:
            # One service per vault, kept across lock/unlock: a backup that finishes after a
            # lock records its result on the live object.
            self.backups = BackupService(service.path, folder, s.backup_keep,
                                         s.backup_min_interval_minutes,
                                         last_success=s.backup_last_success,
                                         last_failure=s.backup_last_failure)
        for listener in (self._after_save_backup, self._remember_last_saved,
                         self._report_damaged_copy):
            if listener not in service.on_saved:
                service.on_saved.append(listener)
        self.window.set_backups_enabled(self.backups.enabled)
        self._backup_status_changed()

    def _backup_status_changed(self) -> None:
        """Keep the "last backup failed" banner and the stored status times up to date."""
        if self.backups is None:
            return
        self.window.set_backup_failure(self.backups.last_failure)
        self.settings.update(backup_last_success=self.backups.last_success,
                             backup_last_failure=self.backups.last_failure)

    def _run_backup(self, prepare: Callable[[], BackupJob | None]) -> None:
        """Back up in the background: the slow folder work never freezes the window (CR-L6)."""
        if self.backups is None:
            return
        if self._backup_busy:
            self._backup_next = prepare  # one at a time; the latest request follows
            return
        try:
            job = prepare()
        except VaultKeeperError as exc:
            self._backup_result(f"Backup failed: {error_text(exc)}")
            return
        if job is None:
            return
        service, idle = self.backups, self._backup_idle
        self._backup_busy = True
        idle.clear()

        def work() -> Path:
            try:
                return run_backup_job(job)
            finally:
                idle.set()  # quit() waits for this

        self._backup_runner.submit(work, lambda _p: self._backup_done(service, job, None),
                                   lambda exc: self._backup_done(service, job, exc))

    def _backup_done(self, service: BackupService, job: BackupJob,
                     exc: BaseException | None) -> None:
        self._backup_busy = False
        error = service.finish(job, exc)
        self._backup_result(f"Backup failed: {error_text(error)}" if error else "Backup saved.")
        follow, self._backup_next = self._backup_next, None
        if follow is not None and service is self.backups:
            self._run_backup(follow)

    def _backup_result(self, text: str) -> None:
        self.window.statusBar().showMessage(text, 10000 if "failed" in text else 4000)
        self._backup_status_changed()

    def _backup_before_quit(self) -> None:
        """Wait (bounded) for a running backup, then make the exit backup here and now."""
        if self.backups is None:
            return
        self._backup_idle.wait(timeout=QUIT_BACKUP_WAIT_SECONDS)
        try:
            if self.backups.on_lock_or_exit() is not None:
                log.info("Exit backup written")
        except VaultKeeperError:
            log.info("Exit backup failed; it is shown after the next start")
        self._backup_status_changed()

    def _report_damaged_copy(self) -> None:
        """Say where a damaged main file was kept (once per copy, CR-L7)."""
        kept = self.service.last_damaged_copy if self.service is not None else None
        if kept is not None and kept != self._reported_damaged:
            self._reported_damaged = kept
            messages.show_warning(self.window, "Damaged file kept",
                                  messages.DAMAGED_COPY_KEPT.format(path=kept))

    def _remember_last_saved(self) -> None:
        if self.service is not None and self.service.is_unlocked:
            record_last_saved(self.settings, self.service)

    def _after_save_backup(self) -> None:
        if self.backups is not None:
            self.backups.dirty = True  # even if it has to wait, lock/exit back this save up
            self._run_backup(self.backups.prepare_after_save)

    def _backup_now(self) -> None:
        if self.backups is not None:
            self._run_backup(self.backups.prepare)

    def _backup_settings(self) -> None:
        if self.backups is None:
            return
        dialog = BackupDialog(self.backups, parent=self.window)
        if run_modal(dialog):
            folder = self.backups.backup_dir
            self.settings.update(backup_dir=str(folder) if folder else None,
                                 backup_keep=self.backups.keep,
                                 backup_min_interval_minutes=self.backups.min_interval_minutes)
        self.window.set_backups_enabled(self.backups.enabled)
        self._backup_status_changed()  # "Backup now" may have run in the dialog

    def _export(self) -> None:
        if self.service is None or not self.service.is_unlocked:
            return
        base = self._new_vault_dir or default_vault_path().parent
        stamp = time.strftime("%Y%m%d")
        default = base / f"VaultKeeper-export-{stamp}{VAULT_EXTENSION}"
        dialog = ExportDialog(dumps_payload(self.service.data), self.service.path,
                              self._runner, self._runner.cancel_pending, default,
                              parent=self.window)
        if run_modal(dialog) and dialog.written_path is not None:
            self.window.statusBar().showMessage("Encrypted export saved.", 6000)

    # --- actions ----------------------------------------------------------------------------

    def _change_password(self) -> None:
        if self.service is None or not self.service.is_unlocked:
            return
        dialog = ChangePasswordDialog(self.service, self._runner.cancel_pending, self.window)
        if run_modal(dialog):
            self.window.banner.setVisible(self.service.opened_from_backup)
            note = after_password_change(self.window, self.backups) if self.backups else ""
            self._backup_status_changed()
            self.window.statusBar().showMessage(f"Master password changed. {note}", 10000)

    def close_dialogs(self) -> None:
        """Close every open dialog (drafts are discarded: locking beats convenience)."""
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                # force_close skips "discard changes?" prompts: locking always wins.
                getattr(widget, "force_close", widget.reject)()

    def _open_settings(self) -> None:
        """Edit timeouts / lock switches; saved and applied at once (Backups has its own)."""
        open_backups = self._backup_settings if self.backups is not None else None
        dialog = SettingsDialog(self.settings.current, open_backups, parent=self.window)
        if not run_modal(dialog):
            return
        # Merged into the current settings: the Backups dialog may have changed them meanwhile.
        saved = self.settings.update(**dialog.values())
        self.guard.apply_settings(self.settings.current)
        self.window.panel.set_reveal_seconds(self.settings.current.show_passwords_seconds)
        self.window.email_tools.domain = self.settings.current.email_domain
        if saved:
            self.window.statusBar().showMessage("Settings saved.", 4000)
        else:
            self.window.statusBar().showMessage(
                "Settings apply now but could not be saved for next time.", 10000)

    def _quick_add_opened(self) -> None:
        """You type from another window while Quick Add is open: use the longer timeout."""
        self.guard.tracker.push_override(self.settings.current.quick_add_autolock_minutes * 60)

    def _auto_lock(self, reason: str) -> None:
        log.info("Auto-lock (%s)", reason)
        self.lock()

    def lock(self) -> None:
        """Close dialogs, drop decrypted state, clear the window, ask for the password again."""
        self.close_dialogs()
        self._runner.cancel_pending()
        self.guard.disarm()  # stops auto-lock and clears our clipboard copy
        if self.backups is not None:  # runs on; only encrypted bytes, result still recorded
            self._run_backup(self.backups.prepare_on_lock_or_exit)
        if self.service is not None:
            self.service.lock()
        self._unlock_minimized = self.window.isMinimized()
        self._remember_geometry()
        self.window.show_locked()
        self.window.hide()  # nothing behind the unlock dialog while locked
        if self.service is not None:
            # Deferred so any dialog event loops we just closed can unwind first.
            QTimer.singleShot(0, self._unlock)

    def quit(self) -> None:
        """Lock (wiping keys) and leave the event loop. Running work is abandoned."""
        self._remember_geometry()
        self._runner.cancel_pending()
        self.guard.disarm()
        self.guard.shutdown()
        self._backup_before_quit()
        if self.service is not None:
            self.service.lock()
        self._instance_lock.release()
        QApplication.quit()

    def _remember_vault(self, path: Path) -> None:
        self.settings.update(vault_path=str(path))

    def _remember_geometry(self) -> None:
        """Keep the main window's size/position for next time (only once it has been shown)."""
        if self.window.isVisible():
            self.settings.update(window_geometry=self.window.geometry_text())
