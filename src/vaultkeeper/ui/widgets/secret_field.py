"""Masked text field with a show/hide toggle (copy button arrives with Phase 5)."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


class SecretField(QWidget):
    """A password-style QLineEdit that is masked by default."""

    textChanged = pyqtSignal(str)
    returnPressed = pyqtSignal()

    def __init__(self, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.edit = QLineEdit(self)
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText(placeholder)
        self.toggle = QPushButton("Show", self)
        self.toggle.setCheckable(True)
        self.toggle.setFocusPolicy(Qt.NoFocus)  # keep it out of the tab order
        self.toggle.toggled.connect(self._set_revealed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.toggle)

        self.edit.textChanged.connect(self.textChanged)
        self.edit.returnPressed.connect(self.returnPressed)
        self.setFocusProxy(self.edit)

    def _set_revealed(self, revealed: bool) -> None:
        self.edit.setEchoMode(QLineEdit.Normal if revealed else QLineEdit.Password)
        self.toggle.setText("Hide" if revealed else "Show")

    @property
    def revealed(self) -> bool:
        """Whether the text is currently shown in clear."""
        return self.edit.echoMode() == QLineEdit.Normal

    def text(self) -> str:
        """Current text."""
        return self.edit.text()

    def setText(self, text: str) -> None:
        """Replace the text."""
        self.edit.setText(text)

    def clear(self) -> None:
        """Empty the field and mask it again."""
        self.edit.clear()
        self.toggle.setChecked(False)
