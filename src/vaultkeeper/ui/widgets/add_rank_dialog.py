"""Quick "add rank" form: name, has divisions? (yes/no), how many. Stays open for the next."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.game_template import MAX_DIVISIONS
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE


class AddRankDialog(QDialog):
    """Calls ``on_add(name, divisions)`` for each rank; Enter adds and clears for the next.

    The divisions choice is kept between ranks, since most ranks in a game share it.
    """

    def __init__(self, on_add: Callable[[str, int], None], existing: list[str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_add = on_add
        self._existing = {name.casefold() for name in existing}
        self.added = 0
        self.setWindowTitle("Add ranks")
        self.setMinimumWidth(360)

        self.name = QLineEdit(self)
        self.name.setPlaceholderText("e.g. Bronze")
        self.has_divisions = QCheckBox("This rank has divisions (like Bronze 1, 2, 3)", self)
        self.count = QSpinBox(self)
        self.count.setRange(1, MAX_DIVISIONS)
        self.count.setValue(3)
        self.count.setEnabled(False)
        hint = QLabel("Add ranks from lowest to highest. Press Enter to add the next one.", self)
        hint.setStyleSheet(MUTED_STYLE)
        hint.setWordWrap(True)
        self.error_label = QLabel(self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.add_button = QPushButton("Add", self)
        self.add_button.setDefault(True)
        self.done_button = QPushButton("Done", self)

        form = QFormLayout()
        form.addRow("Rank name", self.name)
        form.addRow("", self.has_divisions)
        form.addRow("How many?", self.count)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.done_button)
        buttons.addWidget(self.add_button)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self.has_divisions.toggled.connect(self.count.setEnabled)
        self.add_button.clicked.connect(self._add)
        self.name.returnPressed.connect(self._add)
        self.done_button.clicked.connect(self.accept)
        self.name.setFocus()

    def _add(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.error_label.setText("Type a rank name.")
            return
        if name.casefold() in self._existing:
            self.error_label.setText("That rank is already in the list.")
            return
        divisions = self.count.value() if self.has_divisions.isChecked() else 0
        self._on_add(name, divisions)
        self._existing.add(name.casefold())
        self.added += 1
        self.error_label.clear()
        self.name.clear()
        self.name.setFocus()
