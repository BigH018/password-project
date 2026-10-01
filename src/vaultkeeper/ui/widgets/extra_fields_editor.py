"""Extra fields editor: label, type and dropdown options for each user-defined field."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.game_template import CustomField, FieldKind
from vaultkeeper.core.models import new_id

KIND_LABELS = {
    FieldKind.TEXT: "Text",
    FieldKind.NUMBER: "Number",
    FieldKind.CHOICE: "Dropdown",
    FieldKind.SECRET: "Secret (hidden)",
}


class ExtraFieldsEditor(QWidget):
    """Table: Label | Type | Dropdown options (comma-separated). Field ids are preserved."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Label", "Type", "Dropdown options (a, b, c)"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.add_button = QPushButton("Add field", self)
        self.remove_button = QPushButton("Remove", self)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)

        self.add_button.clicked.connect(lambda: self.add_field(None, edit=True))
        self.remove_button.clicked.connect(self._remove)

    def add_field(self, custom: CustomField | None, edit: bool = False) -> None:
        """Append a row for ``custom`` (or a new blank text field)."""
        custom = custom or CustomField(new_id(), "", FieldKind.TEXT)
        row = self.table.rowCount()
        self.table.insertRow(row)
        label = QTableWidgetItem(custom.label)
        label.setData(Qt.UserRole, custom.id)  # keeps values linked when the label changes
        self.table.setItem(row, 0, label)
        kind = QComboBox(self.table)
        for value, text in KIND_LABELS.items():
            kind.addItem(text, value)
        kind.setCurrentIndex(kind.findData(custom.kind))
        self.table.setCellWidget(row, 1, kind)
        self.table.setItem(row, 2, QTableWidgetItem(", ".join(custom.choices)))
        self.table.selectRow(row)
        if edit:
            self.table.editItem(label)

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def load(self, fields: tuple[CustomField, ...]) -> None:
        """Show these fields."""
        self.table.setRowCount(0)
        for custom in fields:
            self.add_field(custom)

    def fields(self) -> list[CustomField]:
        """Current rows as CustomFields (validated later by core)."""
        result = []
        for row in range(self.table.rowCount()):
            label = self.table.item(row, 0)
            kind_box = self.table.cellWidget(row, 1)
            options = self.table.item(row, 2)
            kind = kind_box.currentData() if isinstance(kind_box, QComboBox) else FieldKind.TEXT
            choices: tuple[str, ...] = ()
            if kind is FieldKind.CHOICE and options is not None:
                choices = tuple(o.strip() for o in options.text().split(",") if o.strip())
            result.append(CustomField(
                label.data(Qt.UserRole) if label else new_id(),
                label.text() if label else "",
                kind,
                choices,
            ))
        return result
