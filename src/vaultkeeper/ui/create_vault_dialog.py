"""Create a new vault: location, master password (+ confirm), live strength hint."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.config.constants import VAULT_EXTENSION
from vaultkeeper.core.password_policy import check_master_password
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import WeakPasswordError
from vaultkeeper.ui.messages import error_text
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE
from vaultkeeper.ui.widgets.secret_field import SecretField
from vaultkeeper.ui.widgets.strength_meter import StrengthMeter

ServiceFactory = Callable[[Path], VaultService]
PathChooser = Callable[[QWidget, str], str]


def _choose_save_path(parent: QWidget, current: str) -> str:
    path, _ = QFileDialog.getSaveFileName(
        parent, "Choose where to save your vault", current, f"Vault files (*{VAULT_EXTENSION})"
    )
    return path


class CreateVaultDialog(QDialog):
    """Accepts once the new vault exists and is unlocked (``self.service``)."""

    def __init__(
        self,
        service_factory: ServiceFactory,
        cancel_pending: Callable[[], None],
        default_path: Path,
        choose_path: PathChooser = _choose_save_path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._factory = service_factory
        self._cancel_pending = cancel_pending
        self._choose_path = choose_path
        self._busy = False
        self.service: VaultService | None = None
        self.setWindowTitle("Create a new vault")
        self.setMinimumWidth(480)

        self.path_edit = QLineEdit(str(default_path), self)
        self.browse_button = QPushButton("Browse...", self)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)

        self.password = SecretField("At least 12 characters; a passphrase is best", self)
        self.confirm = SecretField("Type it again", self)
        self.meter = StrengthMeter(self)
        warning = plain_label(
            "There is no way to recover a forgotten master password. Write it down and keep "
            "it somewhere safe and offline.", self)
        warning.setWordWrap(True)
        warning.setStyleSheet(MUTED_STYLE)
        self.error_label = plain_label(parent=self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.busy_bar = QProgressBar(self)
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setFormat("Creating vault...")
        self.busy_bar.setTextVisible(True)
        self.busy_bar.hide()

        self.create_button = QPushButton("Create vault", self)
        self.create_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel", self)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.create_button)

        form = QFormLayout()
        form.addRow("Vault file", path_row)
        form.addRow("Master password", self.password)
        form.addRow("Confirm", self.confirm)
        form.addRow("", self.meter)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(warning)
        layout.addWidget(self.error_label)
        layout.addWidget(self.busy_bar)
        layout.addLayout(buttons)

        self.password.textChanged.connect(self.meter.update_for)
        self.browse_button.clicked.connect(self._browse)
        self.create_button.clicked.connect(self._start)
        self.confirm.returnPressed.connect(self._start)
        self.cancel_button.clicked.connect(self.reject)
        self.password.setFocus()

    @property
    def busy(self) -> bool:
        """True while the key derivation is running."""
        return self._busy

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.path_edit, self.browse_button, self.password, self.confirm,
                       self.create_button):
            widget.setEnabled(not busy)
        self.busy_bar.setVisible(busy)

    def _browse(self) -> None:
        chosen = self._choose_path(self, self.path_edit.text())
        if chosen:
            self.path_edit.setText(chosen)

    def _target_path(self) -> Path | None:
        text = self.path_edit.text().strip()
        if not text:
            self.error_label.setText("Choose where to save the vault file.")
            return None
        path = Path(text)
        if path.suffix.lower() != VAULT_EXTENSION:
            path = path.with_name(path.name + VAULT_EXTENSION)
        if path.exists():
            self.error_label.setText(
                "A file already exists there. Choose another name, or cancel and open it.")
            return None
        return path

    def _start(self) -> None:
        if self._busy:
            return
        path = self._target_path()
        if path is None:
            return
        password = self.password.text()
        if password != self.confirm.text():
            self.error_label.setText("The two passwords don't match.")
            return
        try:
            check_master_password(password)
        except WeakPasswordError as exc:
            self.error_label.setText(error_text(exc))
            return
        self.error_label.clear()
        self.service = self._factory(path)
        self._set_busy(True)
        self.service.create_async(password, self._on_created, self._on_failed)

    def _on_created(self) -> None:
        self._set_busy(False)
        self.password.clear()
        self.confirm.clear()
        self.accept()

    def _on_failed(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.service = None
        self.error_label.setText(error_text(exc))

    def reject(self) -> None:
        """Close. A running creation is abandoned; no vault file is written."""
        if self._busy:
            self._cancel_pending()
            self._set_busy(False)
            self.service = None
        self.password.clear()
        self.confirm.clear()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Window close button behaves like Cancel (never blocked)."""
        self.reject()
        event.accept()
