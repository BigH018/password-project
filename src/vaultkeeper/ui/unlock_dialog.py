"""Master password prompt, with an explicit (never automatic) offer to open the backup copy.

Argon2 runs on the task runner's background thread. While it works the inputs are
disabled and a busy bar shows, but the dialog can still be closed: closing discards the
result (``cancel_pending``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.config.constants import WINDOW_TITLE
from vaultkeeper.config.settings import SettingsFile
from vaultkeeper.core.vault_disk import remember_saved_at, vault_key, went_back_in_time
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import VaultAuthError, VaultFormatError
from vaultkeeper.ui import messages
from vaultkeeper.ui.messages import error_text, local_time_text
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE
from vaultkeeper.ui.welcome_dialog import FileChooser, choose_vault_file
from vaultkeeper.ui.widgets.secret_field import SecretField

BACKUP_EXPLANATION = (
    "Only use this if you're sure your password is right. It opens the previously saved "
    "version of your vault. The current file is kept, not deleted."
)


class UnlockDialog(QDialog):
    """Accepts once the vault is unlocked.

    If the user picks a different vault file instead (small link at the bottom, for restoring
    a backup or a moved vault), the dialog rejects with ``other_vault_path`` set.
    """

    def __init__(
        self,
        service: VaultService,
        cancel_pending: Callable[[], None],
        choose_file: FileChooser = choose_vault_file,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._cancel_pending = cancel_pending
        self._choose_file = choose_file
        self._busy = False
        self.other_vault_path: Path | None = None
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumWidth(440)

        self.path_label = plain_label(f"Vault: {service.path}", self)
        self.path_label.setStyleSheet(MUTED_STYLE)
        self.path_label.setWordWrap(True)
        self.password = SecretField("Master password", self)
        self.error_label = plain_label(parent=self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.busy_bar = QProgressBar(self)
        self.busy_bar.setRange(0, 0)  # indeterminate
        self.busy_bar.setFormat("Unlocking...")
        self.busy_bar.setTextVisible(True)
        self.busy_bar.hide()

        self.backup_button = QPushButton("Try the backup copy", self)
        self.backup_note = plain_label(BACKUP_EXPLANATION, self)
        self.backup_note.setWordWrap(True)
        self.backup_note.setStyleSheet(MUTED_STYLE)
        self.backup_button.hide()
        self.backup_note.hide()

        self.other_button = QPushButton("Open a different vault file...", self)
        self.other_button.setFlat(True)  # deliberately low-key: one vault is the normal case
        self.other_button.setStyleSheet(MUTED_STYLE + " text-decoration: underline;")
        self.unlock_button = QPushButton("Unlock", self)
        self.unlock_button.setDefault(True)
        self.quit_button = QPushButton("Quit", self)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.quit_button)
        buttons.addWidget(self.unlock_button)
        footer = QHBoxLayout()
        footer.addWidget(self.other_button)
        footer.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(plain_label("Enter your master password to unlock the vault.", self))
        layout.addWidget(self.path_label)
        layout.addWidget(self.password)
        layout.addWidget(self.error_label)
        layout.addWidget(self.busy_bar)
        layout.addWidget(self.backup_button)
        layout.addWidget(self.backup_note)
        layout.addLayout(buttons)
        layout.addLayout(footer)

        self.unlock_button.clicked.connect(lambda: self._start(use_backup=False))
        self.password.returnPressed.connect(lambda: self._start(use_backup=False))
        self.backup_button.clicked.connect(lambda: self._start(use_backup=True))
        self.other_button.clicked.connect(self._choose_other)
        self.quit_button.clicked.connect(self.reject)
        self.password.setFocus()

    # --- state --------------------------------------------------------------------------

    @property
    def busy(self) -> bool:
        """True while a key derivation is running."""
        return self._busy

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.password, self.unlock_button, self.backup_button, self.other_button):
            widget.setEnabled(not busy)
        self.busy_bar.setVisible(busy)
        # Quit stays enabled on purpose: the user can always walk away.

    # --- actions ------------------------------------------------------------------------

    def _start(self, *, use_backup: bool) -> None:
        if self._busy:
            return
        password = self.password.text()
        if not password:
            self.error_label.setText("Enter your master password.")
            return
        self.error_label.clear()
        self.password.clear()
        self._set_busy(True)
        self._service.unlock_async(
            password, self._on_unlocked, self._on_failed, use_backup=use_backup
        )

    def _on_unlocked(self) -> None:
        self._set_busy(False)
        self.accept()

    def _on_failed(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.error_label.setText(error_text(exc))
        if isinstance(exc, VaultAuthError | VaultFormatError) and self._service.has_backup():
            self.backup_button.show()
            self.backup_note.show()
        self.password.setFocus()

    def _choose_other(self) -> None:
        chosen = self._choose_file(self)
        if chosen:  # cancelled picker: stay on this screen
            self.other_vault_path = Path(chosen)
            self.reject()

    # --- closing during work discards the result ------------------------------------------

    def reject(self) -> None:
        """Close. Any running unlock is abandoned and its result discarded."""
        if self._busy:
            self._cancel_pending()
            self._set_busy(False)
        self.password.clear()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Window close button behaves like Quit (never blocked)."""
        self.reject()
        event.accept()


# --- after unlocking: "Last saved" and the went-back-in-time check (SEC-M3) ---------------
OLDER_COPY = (
    "This vault file was last saved {file_time}, but this PC has already seen a newer "
    "version (saved {seen_time}).\n\n"
    "It may be an old copy or a backup that was put back in its place. If you didn't restore "
    "it on purpose, check your vault and backup files before making changes.")


def record_last_saved(settings: SettingsFile, service: VaultService) -> None:
    """Remember the vault's last-saved time for this PC (a timestamp, nothing secret)."""
    settings.update(vault_last_saved=remember_saved_at(
        settings.current.vault_last_saved, service.path, service.data.updated_at))


def check_last_saved(parent: QWidget | None, settings: SettingsFile,
                     service: VaultService) -> str:
    """Warn once if the vault is older than the version this PC saw last (not when opened
    from ``.bak``, which is older by design), remember its time, return a status line."""
    updated = service.data.updated_at
    seen = settings.current.vault_last_saved.get(vault_key(service.path))
    if not service.opened_from_backup and seen and went_back_in_time(seen, updated):
        messages.show_warning(parent, "Older vault file", OLDER_COPY.format(
            file_time=local_time_text(updated), seen_time=local_time_text(seen)))
    record_last_saved(settings, service)
    return f"Last saved: {local_time_text(updated)}." if updated else ""

