"""Email generator dialog: game name, random length, preview, copy or use.

Thin: addresses come from ``core.email_generator``. The dialog asks for the game name, shows
the result and hands it to the account form ("Use this email") or the clipboard ("Copy").
"""

from __future__ import annotations

from collections.abc import Callable, Collection

from PyQt5.QtGui import QFont
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

from vaultkeeper.config.constants import DEFAULT_EMAIL_DOMAIN
from vaultkeeper.core import email_generator as eg
from vaultkeeper.errors import ValidationError
from vaultkeeper.ui.messages import error_text, run_modal
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE

Taken = Callable[[], Collection[str]]


class EmailGeneratorDialog(QDialog):
    """``email`` holds the result when accepted via "Use this email"."""

    def __init__(self, domain: str, taken: Taken, game_name: str = "",
                 copy: Callable[[str], None] | None = None, allow_use: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._domain = domain
        self._taken = taken
        self._copy = copy
        self.email = ""
        self.setWindowTitle("Generate email")
        self.setMinimumWidth(460)

        self.game_name = QLineEdit(game_name, self)
        self.game_name.setPlaceholderText("e.g. Valorant")
        self.length = QSpinBox(self)
        self.length.setRange(eg.MIN_LENGTH, eg.MAX_LENGTH)
        self.length.setValue(eg.DEFAULT_LENGTH)
        self.length.setSuffix(" characters")
        self.preview = QLineEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 11))
        self.hint = plain_label(
            f"gamename.random@{domain}  (change the domain in File -> Settings)", self)
        self.hint.setStyleSheet(MUTED_STYLE)
        self.error_label = plain_label(parent=self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.regenerate_button = QPushButton("Regenerate", self)
        self.copy_button = QPushButton("Copy", self)
        self.copy_button.setVisible(copy is not None)
        self.use_button = QPushButton("Use this email", self)
        self.use_button.setVisible(allow_use)
        self.use_button.setDefault(allow_use)
        self.close_button = QPushButton("Close", self)

        form = QFormLayout()
        form.addRow("Game name", self.game_name)
        form.addRow("Random part", self.length)
        buttons = QHBoxLayout()
        buttons.addWidget(self.regenerate_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.use_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(self.hint)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self.game_name.textChanged.connect(self.regenerate)
        self.length.valueChanged.connect(self.regenerate)
        self.regenerate_button.clicked.connect(self.regenerate)
        self.copy_button.clicked.connect(self._copy_current)
        self.use_button.clicked.connect(self._use)
        self.close_button.clicked.connect(self.reject)
        self.regenerate()
        self.game_name.setFocus()

    def regenerate(self) -> None:
        """Make a new address that isn't already saved in the vault."""
        try:
            self.preview.setText(eg.generate_email(self.game_name.text(), self._domain,
                                                   self._taken(), self.length.value()))
            self.error_label.clear()
        except ValidationError as exc:
            self.preview.clear()
            self.error_label.setText(error_text(exc))
        has = bool(self.preview.text())
        self.copy_button.setEnabled(has)
        self.use_button.setEnabled(has)

    def _copy_current(self) -> None:
        if self._copy is not None and self.preview.text():
            self._copy(self.preview.text())

    def _use(self) -> None:
        self.email = self.preview.text()
        if self.email:
            self.accept()


class EmailGeneratorLauncher:
    """Opens the email generator with the vault's addresses, the domain setting and copy."""

    def __init__(self, taken: Taken, copy: Callable[[str], None],
                 domain: str = DEFAULT_EMAIL_DOMAIN) -> None:
        self.domain = domain  # the controller keeps this in step with the settings
        self._taken = taken
        self._copy = copy

    def open(self, game_name: str = "", parent: QWidget | None = None) -> None:
        """Generate and copy (Tools menu)."""
        run_modal(EmailGeneratorDialog(self.domain, self._taken, game_name, copy=self._copy,
                                       parent=parent))

    def pick(self, game_name: str, parent: QWidget | None = None) -> str:
        """Generate for the account form: the chosen address, or "" if closed."""
        dialog = EmailGeneratorDialog(self.domain, self._taken, game_name, copy=self._copy,
                                      allow_use=True, parent=parent)
        return dialog.email if run_modal(dialog) else ""
