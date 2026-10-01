"""Backup settings (folder, keep N, interval) plus "Backup now"."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
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
from vaultkeeper.ui.messages import error_text
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE, WARNING_BANNER_STYLE

FolderChooser = Callable[[QWidget, str], str]


def _choose_folder(parent: QWidget, current: str) -> str:
    return QFileDialog.getExistingDirectory(parent, "Choose a backup folder", current)


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
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self.browse_button.clicked.connect(self._browse)
        self.folder.textChanged.connect(self._apply_to_service)
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

    def _apply_to_service(self) -> None:
        self._backups.configure(self.folder_path, self.keep_spin.value(),
                                self.interval_spin.value())
        self._refresh()

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
        existing = self._backups.list_backups()
        self.status.setText(f"{len(existing)} backup(s) in this folder. Newest: "
                            f"{existing[-1].name}" if existing else "No backups yet.")
        self.backup_now_button.setEnabled(self._backups.enabled)

    # --- actions ----------------------------------------------------------------------------

    def _browse(self) -> None:
        chosen = self._choose(self, self.folder.text())
        if chosen:
            self.folder.setText(chosen)

    def _backup_now(self) -> None:
        try:
            self._backups.backup_now()
        except VaultKeeperError as exc:
            self.error_label.setText(error_text(exc))
            return
        self.error_label.clear()
        self._refresh()

    def reject(self) -> None:
        """Cancel: put the previous settings back."""
        self._backups.configure(*self._original)
        super().reject()
