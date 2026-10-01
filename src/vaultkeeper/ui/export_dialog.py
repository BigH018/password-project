"""Encrypted export: target file + a separate export password. KDF runs off the UI thread."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.exporter import check_export_path, write_export
from vaultkeeper.core.password_policy import check_master_password
from vaultkeeper.core.tasks import TaskRunner
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui.file_pickers import choose_save_file
from vaultkeeper.ui.messages import error_text
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE
from vaultkeeper.ui.widgets.secret_field import SecretField
from vaultkeeper.ui.widgets.strength_meter import StrengthMeter

PathChooser = Callable[[QWidget, str], str]


def _choose_path(parent: QWidget, current: str) -> str:
    return choose_save_file(parent, "Export to", current)


class ExportDialog(QDialog):
    """Accepts after the export file is written and verified (``written_path``)."""

    def __init__(
        self,
        payload: bytes,
        vault_path: Path,
        runner: TaskRunner,
        cancel_pending: Callable[[], None],
        default_path: Path,
        writer: Callable[..., bool] = write_export,
        choose_path: PathChooser = _choose_path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._payload = payload
        self._vault_path = vault_path
        self._runner = runner
        self._cancel_pending = cancel_pending
        self._writer = writer
        self._choose = choose_path
        self._busy = False
        self._cancel_flag = [False]
        self.written_path: Path | None = None
        self.setWindowTitle("Export encrypted copy")
        self.setMinimumWidth(500)

        intro = plain_label("Creates an encrypted copy of your whole vault, protected by a "
                            "separate export password. It never contains plaintext.", self)
        intro.setWordWrap(True)
        intro.setStyleSheet(MUTED_STYLE)
        self.path_edit = QLineEdit(str(default_path), self)
        self.browse_button = QPushButton("Browse...", self)
        self.overwrite = QCheckBox("Replace the file if it already exists", self)
        self.password = SecretField("Export password (at least 12 characters)", self)
        self.confirm = SecretField("Type it again", self)
        self.meter = StrengthMeter(self)
        self.error_label = plain_label(parent=self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.busy_bar = QProgressBar(self)
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setFormat("Encrypting...")
        self.busy_bar.setTextVisible(True)
        self.busy_bar.hide()
        self.export_button = QPushButton("Export", self)
        self.export_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel", self)

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self.browse_button)
        form = QFormLayout()
        form.addRow("Export file", path_row)
        form.addRow("", self.overwrite)
        form.addRow("Export password", self.password)
        form.addRow("Confirm", self.confirm)
        form.addRow("", self.meter)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.export_button)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.busy_bar)
        layout.addLayout(buttons)

        self.password.textChanged.connect(self.meter.update_for)
        self.browse_button.clicked.connect(self._browse)
        self.export_button.clicked.connect(self._start)
        self.cancel_button.clicked.connect(self.reject)

    @property
    def busy(self) -> bool:
        """True while encrypting/writing."""
        return self._busy

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in (self.path_edit, self.browse_button, self.overwrite, self.password,
                       self.confirm, self.export_button):
            widget.setEnabled(not busy)
        self.busy_bar.setVisible(busy)

    def _browse(self) -> None:
        chosen = self._choose(self, self.path_edit.text())
        if chosen:
            self.path_edit.setText(chosen)

    def _start(self) -> None:
        if self._busy:
            return
        password = self.password.text()
        try:
            target = check_export_path(Path(self.path_edit.text().strip() or "export"),
                                       self._vault_path, self.overwrite.isChecked())
            if password != self.confirm.text():
                self.error_label.setText("The two passwords don't match.")
                return
            check_master_password(password)
        except VaultKeeperError as exc:
            self.error_label.setText(error_text(exc))
            return
        self.error_label.clear()
        self._set_busy(True)
        payload, writer = self._payload, self._writer
        flag = self._cancel_flag = [False]  # fresh flag per attempt
        self._runner.submit(lambda: writer(payload, target, password, cancelled=lambda: flag[0]),
                            lambda _r: self._done(target), self._failed)

    def _done(self, target: Path) -> None:
        self._set_busy(False)
        self.written_path = target
        self._clear()
        self.accept()

    def _failed(self, exc: BaseException) -> None:
        self._set_busy(False)
        self.error_label.setText(error_text(exc))

    def _clear(self) -> None:
        self.password.clear()
        self.confirm.clear()

    def reject(self) -> None:
        """Close. A running export is abandoned (its result is discarded)."""
        if self._busy:
            self._cancel_flag[0] = True  # the worker skips writing once its KDF finishes
            self._cancel_pending()
            self._set_busy(False)
        self._clear()
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Window close button behaves like Cancel."""
        self.reject()
        event.accept()
