"""Backup settings (folder, keep N, interval) plus "Backup now"."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.config import constants as c
from vaultkeeper.core.backup import BackupService
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui import messages
from vaultkeeper.ui.file_pickers import choose_folder
from vaultkeeper.ui.messages import error_text, local_time_text
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE, WARNING_BANNER_STYLE

FolderChooser = Callable[[QWidget, str], str]
FOLDER_PAUSE_MS = 400  # list the folder once typing pauses, not on every keystroke
UNREADABLE_FOLDER = "Can't read this folder. Check that it exists and that you can open it."
OLD_BACKUPS_TEXT = (
    "{count} older backup(s) in your backup folder still open with your OLD master "
    "password.\n\nA backup with your new password was just made. Delete the older ones now?")


def after_password_change(parent: QWidget | None, backups: BackupService) -> str:
    """Back up at once, then offer to delete backups that open with the old password.

    Deletion is only offered once a backup with the new password exists. Returns a status
    line for the window ("" if backups are off and there is nothing to say).
    """
    if not backups.enabled:
        return ""
    try:
        backups.after_password_change()
    except VaultKeeperError as exc:
        failed = f"Backup failed: {error_text(exc)} "
    else:
        failed = ""
    old = backups.backups_with_old_password()
    if not old:
        return failed or "Backup saved with your new master password."
    kept = f"{failed}{len(old)} older backup(s) still open with your old master password."
    if not backups.has_backup_with_current_password():
        return kept
    if not messages.confirm(parent, "Older backups", OLD_BACKUPS_TEXT.format(count=len(old)),
                            ok_text="Delete older backups"):
        return kept
    return f"Deleted {backups.delete_backups(old)} older backup(s)."


def _choose_folder(parent: QWidget, current: str) -> str:
    return choose_folder(parent, "Choose a backup folder", current)


class BackupDialog(QDialog):
    """Accepting returns the chosen settings in ``folder``, ``keep``, ``interval``."""

    def __init__(self, backups: BackupService, choose_folder: FolderChooser = _choose_folder,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._backups = backups
        self._choose = choose_folder
        self.setWindowTitle("Backups")
        self.setMinimumWidth(520)

        intro = plain_label("Backups are encrypted copies of your vault (same master password). "
                            "Pick a folder on another drive or a USB stick if you can.", self)
        intro.setWordWrap(True)
        intro.setStyleSheet(MUTED_STYLE)
        self.folder = QLineEdit(str(backups.backup_dir or ""), self)
        self.folder.setPlaceholderText("No backup folder chosen: backups are OFF")
        self.browse_button = QPushButton("Browse...", self)
        self.keep_spin = QSpinBox(self)
        self.keep_spin.setRange(*c.BACKUP_KEEP_RANGE)
        self.keep_spin.setValue(backups.keep)
        self.interval_spin = QSpinBox(self)
        self.interval_spin.setRange(*c.BACKUP_MIN_INTERVAL_MINUTES_RANGE)
        self.interval_spin.setValue(backups.min_interval_minutes)
        self.interval_spin.setSuffix(" min")
        self.warning = plain_label(parent=self)
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(WARNING_BANNER_STYLE)
        self.status = plain_label(parent=self)
        self.status.setStyleSheet(MUTED_STYLE)
        self.last_backup = plain_label(parent=self)
        self.last_backup.setStyleSheet(MUTED_STYLE)
        self.error_label = plain_label(parent=self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.backup_now_button = QPushButton("Backup now", self)
        self.save_button = QPushButton("Save", self)
        self.save_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel", self)

        folder_row = QHBoxLayout()
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(self.browse_button)
        form = QFormLayout()
        form.addRow("Backup folder", folder_row)
        form.addRow("Keep the newest", self.keep_spin)
        form.addRow("At most one per", self.interval_spin)
        buttons = QHBoxLayout()
        buttons.addWidget(self.backup_now_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.warning)
        layout.addWidget(self.status)
        layout.addWidget(self.last_backup)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        # Typing restarts this timer; the folder is checked and listed once the user pauses.
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(FOLDER_PAUSE_MS)
        self.refresh_timer.timeout.connect(self._apply_to_service)
        self.browse_button.clicked.connect(self._browse)
        self.folder.textChanged.connect(self.refresh_timer.start)
        self.keep_spin.valueChanged.connect(self._apply_to_service)
        self.interval_spin.valueChanged.connect(self._apply_to_service)
        self.backup_now_button.clicked.connect(self._backup_now)
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self._original = (backups.backup_dir, backups.keep, backups.min_interval_minutes)
        self._refresh()

    # --- values -----------------------------------------------------------------------------

    @property
    def folder_path(self) -> Path | None:
        """The chosen folder, or None (backups off)."""
        text = self.folder.text().strip()
        return Path(text) if text else None

    def _apply_to_service(self) -> bool:
        """Apply the form to the backup service. False (with a message) if it was refused,
        e.g. a folder that isn't a full path."""
        self.refresh_timer.stop()
        try:
            self._backups.configure(self.folder_path, self.keep_spin.value(),
                                    self.interval_spin.value())
        except VaultKeeperError as exc:
            self.error_label.setText(error_text(exc))
            self._refresh()
            return False
        self.error_label.clear()
        self._refresh()
        return True

    def _refresh(self) -> None:
        if not self._backups.enabled:
            self.warning.setText("Backups are OFF. Choose a folder before entering real accounts.")
            self.warning.show()
        elif self._backups.same_folder_as_vault():
            self.warning.setText("This is the same folder as your vault. If that drive fails "
                                 "you lose both. A different drive is much safer.")
            self.warning.show()
        else:
            self.warning.hide()
        try:
            existing = self._backups.list_backups()
        except VaultKeeperError:
            self.status.setText(UNREADABLE_FOLDER)
        else:
            self.status.setText(f"{len(existing)} backup(s) in this folder. Newest: "
                                f"{existing[-1].name}" if existing else "No backups yet.")
        self.backup_now_button.setEnabled(self._backups.enabled)
        ok, failed = self._backups.last_success, self._backups.last_failure
        line = (f"Last successful backup: {local_time_text(ok)}." if ok
                else "No successful backup yet.")
        if failed:
            line += f" The last attempt failed at {local_time_text(failed)}."
        self.last_backup.setText(line)

    # --- actions ----------------------------------------------------------------------------

    def _browse(self) -> None:
        chosen = self._choose(self, self.folder.text())
        if chosen:
            self.folder.setText(chosen)
            self._apply_to_service()  # a picked folder needs no typing pause

    def _backup_now(self) -> None:
        if not self._apply_to_service():
            return
        try:
            self._backups.backup_now()
        except VaultKeeperError as exc:
            self.error_label.setText(error_text(exc))
            self._refresh()
            return
        self.error_label.clear()
        self._refresh()

    def accept(self) -> None:
        """Save: apply what's typed now; stay open if it's refused (e.g. not a full path)."""
        if self._apply_to_service():
            super().accept()

    def reject(self) -> None:
        """Cancel: put the previous settings back exactly as they were."""
        self.refresh_timer.stop()
        b = self._backups
        b.backup_dir, b.keep, b.min_interval_minutes = self._original
        super().reject()
