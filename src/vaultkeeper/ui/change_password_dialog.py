"""Change the master password: current, new, confirm, strength hint. KDF runs off-thread."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.password_policy import check_master_password
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import WeakPasswordError
from vaultkeeper.ui.messages import error_text
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE
from vaultkeeper.ui.widgets.secret_field import SecretField
from vaultkeeper.ui.widgets.strength_meter import StrengthMeter


class ChangePasswordDialog(QDialog):
    """Accepts once the vault has been re-encrypted with the new password."""

    def __init__(
        self,
        service: VaultService,
        cancel_pending: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._cancel_pending = cancel_pending
        self._busy = False
        self.setWindowTitle("Change master password")
        self.setMinimumWidth(460)

        self.current = SecretField("Current master password", self)
        self.new = SecretField("At least 12 characters; a passphrase is best", self)
        self.confirm = SecretField("Type the new password again", self)
        self.meter = StrengthMeter(self)
        note = plain_label("The vault is re-encrypted with a fresh salt. There is no way to "
                           "recover a forgotten master password.", self)
        note.setWordWrap(True)
        note.setStyleSheet(MUTED_STYLE)
        self.error_label = plain_label(parent=self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.busy_bar = QProgressBar(self)
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setFormat("Re-encrypting...")
        self.busy_bar.setTextVisible(True)
        self.busy_bar.hide()
        self.change_button = QPushButton("Change password", self)
        self.change_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel", self)

        form = QFormLayout()
        form.addRow("Current", self.current)
        form.addRow("New", self.new)
        form.addRow("Confirm new", self.confirm)
        form.addRow("", self.meter)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.change_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(self.error_label)
        layout.addWidget(self.busy_bar)
        layout.addLayout(buttons)

        self.new.textChanged.connect(self.meter.update_for)
        self.change_button.clicked.connect(self._start)
        self.confirm.returnPressed.connect(self._start)
        self.cancel_button.clicked.connect(self.reject)
        self.current.setFocus()

    @property
    def busy(self) -> bool:
        """True while the key derivations run."""
        return self._busy

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.current, self.new, self.confirm, self.change_button):
            widget.setEnabled(not busy)
        self.busy_bar.setVisible(busy)

    def _start(self) -> None:
        if self._busy:
            return
        current, new = self.current.text(), self.new.text()
        if not current:
            self.error_label.setText("Enter your current master password.")
            return
        if new != self.confirm.text():
            self.error_label.setText("The two new passwords don't match.")
            return
        if new == current:
            self.error_label.setText("The new password must be different from the current one.")
            return
        try:
            check_master_password(new)
        except WeakPasswordError as exc:
            self.error_label.setText(error_text(exc))
            return
        self.error_label.clear()
        self._set_busy(True)
        self._service.change_password_async(current, new, self._on_done, self._on_failed)

    def _on_done(self) -> None:
        self._set_busy(False)
        self._clear_fields()
        self.accept()

    def _on_failed(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.current.clear()
        self.error_label.setText(error_text(exc))
        self.current.setFocus()

    def _clear_fields(self) -> None:
        for field in (self.current, self.new, self.confirm):
            field.clear()

    def reject(self) -> None:
        """Close. A running change is abandoned and the password stays as it was."""
        if self._busy:
            self._cancel_pending()
            self._set_busy(False)
        self._clear_fields()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Window close button behaves like Cancel (never blocked)."""
        self.reject()
        event.accept()
