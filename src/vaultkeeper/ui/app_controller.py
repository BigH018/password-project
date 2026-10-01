"""Screen flow: Welcome -> Create/Unlock -> Main window, and Lock -> Unlock.

UI wiring only. All decisions about vault state live in ``VaultService``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PyQt5.QtCore import QObject, QStandardPaths
from PyQt5.QtWidgets import QApplication

from vaultkeeper.config.constants import VAULT_EXTENSION
from vaultkeeper.config.settings import Settings, save_settings, update_settings
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import VaultIOError
from vaultkeeper.ui.create_vault_dialog import CreateVaultDialog
from vaultkeeper.ui.main_window import MainWindow
from vaultkeeper.ui.qt_adapters import QtTaskRunner
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
    ) -> None:
        super().__init__()
        self._new_vault_dir = new_vault_dir
        self._settings = settings
        self._settings_file = settings_file
        self._runner = runner
        self._factory = service_factory
        self.service: VaultService | None = None
        self.window = MainWindow(demo=demo)
        self.window.lock_requested.connect(self.lock)
        self.window.quit_requested.connect(self.quit)

    # --- flow -------------------------------------------------------------------------------

    def start(self) -> None:
        """Entry point once the Qt event loop is running."""
        self.window.show()
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
        elif dialog.wants_other_vault:
            self.service = None
            self._welcome()
        else:
            self.quit()

    def _show_unlocked(self) -> None:
        if self.service is None:
            return
        self.window.show_unlocked(str(self.service.path), self.service.opened_from_backup)

    # --- actions ----------------------------------------------------------------------------

    def lock(self) -> None:
        """Drop decrypted state, clear the window, ask for the password again."""
        if self.service is not None:
            self.service.lock()
        self.window.show_locked()
        if self.service is not None:
            self._unlock()

    def quit(self) -> None:
        """Lock (wiping keys) and leave the event loop. Running work is abandoned."""
        self._runner.cancel_pending()
        if self.service is not None:
            self.service.lock()
        QApplication.quit()

    def _remember_vault(self, path: Path) -> None:
        if self._settings.vault_path == str(path):
            return
        self._settings = update_settings(self._settings, vault_path=str(path))
        try:
            save_settings(self._settings_file, self._settings)
        except VaultIOError:
            log.warning("Could not save settings; the vault location won't be remembered")
