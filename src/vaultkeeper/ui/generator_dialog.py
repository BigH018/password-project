"""Password generator dialog: options, live preview, strength, copy or use."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core import generator as g
from vaultkeeper.errors import ValidationError
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE


class GeneratorDialog(QDialog):
    """``password`` holds the result when accepted via "Use this password"."""

    def __init__(self, copy: Callable[[str], None] | None = None, allow_use: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._copy = copy
        self.password = ""
        self.setWindowTitle("Generate password")
        self.setMinimumWidth(460)

        self.length = QSpinBox(self)
        self.length.setRange(g.MIN_LENGTH, g.MAX_LENGTH)
        self.length.setValue(g.DEFAULT_LENGTH)
        self.slider = QSlider(self)
        self.slider.setOrientation(Qt.Horizontal)
        self.slider.setRange(g.MIN_LENGTH, 64)
        self.slider.setValue(g.DEFAULT_LENGTH)
        self.lower = QCheckBox("a-z", self)
        self.upper = QCheckBox("A-Z", self)
        self.digits = QCheckBox("0-9", self)
        self.symbols = QCheckBox("Symbols", self)
        self.ambiguous = QCheckBox("Avoid look-alikes (I l 1 O 0)", self)
        for box in (self.lower, self.upper, self.digits, self.symbols, self.ambiguous):
            box.setChecked(True)
        self.preview = QLineEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 11))
        self.strength = plain_label(parent=self)
        self.strength.setStyleSheet(MUTED_STYLE)
        self.error_label = plain_label(parent=self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.regenerate_button = QPushButton("Regenerate", self)
        self.copy_button = QPushButton("Copy", self)
        self.copy_button.setVisible(copy is not None)
        self.use_button = QPushButton("Use this password", self)
        self.use_button.setVisible(allow_use)
        self.use_button.setDefault(allow_use)
        self.close_button = QPushButton("Close", self)

        length_row = QHBoxLayout()
        length_row.addWidget(self.slider, 1)
        length_row.addWidget(self.length)
        classes = QHBoxLayout()
        for box in (self.lower, self.upper, self.digits, self.symbols):
            classes.addWidget(box)
        form = QFormLayout()
        form.addRow("Length", length_row)
        form.addRow("Characters", classes)
        form.addRow("", self.ambiguous)
        buttons = QHBoxLayout()
        buttons.addWidget(self.regenerate_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.use_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.preview)
        layout.addWidget(self.strength)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self.slider.valueChanged.connect(self.length.setValue)
        self.length.valueChanged.connect(self._length_changed)
        for box in (self.lower, self.upper, self.digits, self.symbols, self.ambiguous):
            box.toggled.connect(self.regenerate)
        self.regenerate_button.clicked.connect(self.regenerate)
        self.copy_button.clicked.connect(self._copy_current)
        self.use_button.clicked.connect(self._use)
        self.close_button.clicked.connect(self.reject)
        self.regenerate()

    def options(self) -> g.GeneratorOptions:
        """Options from the controls."""
        return g.GeneratorOptions(
            length=self.length.value(), lowercase=self.lower.isChecked(),
            uppercase=self.upper.isChecked(), digits=self.digits.isChecked(),
            symbols=self.symbols.isChecked(), avoid_ambiguous=self.ambiguous.isChecked(),
        )

    def _length_changed(self, value: int) -> None:
        if self.slider.minimum() <= value <= self.slider.maximum():
            self.slider.blockSignals(True)
            self.slider.setValue(value)
            self.slider.blockSignals(False)
        self.regenerate()

    def regenerate(self) -> None:
        """Make a new password with the current options."""
        try:
            self.preview.setText(g.generate(self.options()))
            self.strength.setText(f"About {g.entropy_bits(self.options())} bits of randomness")
            self.error_label.clear()
        except ValidationError as exc:
            self.preview.clear()
            self.strength.clear()
            self.error_label.setText(f"{exc.reason.capitalize()}.")
        has = bool(self.preview.text())
        self.copy_button.setEnabled(has)
        self.use_button.setEnabled(has)

    def _copy_current(self) -> None:
        if self._copy is not None and self.preview.text():
            self._copy(self.preview.text())

    def _use(self) -> None:
        self.password = self.preview.text()
        if self.password:
            self.accept()

    def done(self, result: int) -> None:
        """Clear the preview on close so the text doesn't linger in a hidden widget."""
        self.preview.clear()
        super().done(result)
