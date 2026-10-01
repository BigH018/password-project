"""Rank list editor: tiers in order (lowest first), divisions per tier, division style."""

from __future__ import annotations

from typing import Any

from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.game_template import MAX_DIVISIONS, GameTemplate, TierDef


class LadderEditor(QWidget):
    """Table of rank names + division counts, with add/remove/reorder and style options."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Rank (lowest first)", "Divisions"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.add_button = QPushButton("Add rank", self)
        self.remove_button = QPushButton("Remove", self)
        self.up_button = QPushButton("Up", self)
        self.down_button = QPushButton("Down", self)
        self.best_is_one = QCheckBox("Division 1 is the best (like Overwatch)", self)
        self.roman = QCheckBox("Show divisions as I, II, III", self)

        buttons = QHBoxLayout()
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        layout.addWidget(self.best_is_one)
        layout.addWidget(self.roman)

        self.add_button.clicked.connect(lambda: self.add_tier("", 0, edit=True))
        self.remove_button.clicked.connect(self._remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))

    # --- rows -------------------------------------------------------------------------------

    def add_tier(self, name: str, divisions: int, edit: bool = False) -> None:
        """Append a tier row (optionally start editing its name)."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        spin = QSpinBox(self.table)
        spin.setRange(0, MAX_DIVISIONS)
        spin.setValue(divisions)
        spin.setSpecialValueText("none")
        self.table.setCellWidget(row, 1, spin)
        self.table.selectRow(row)
        if edit:
            self.table.editItem(self.table.item(row, 0))

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _move(self, step: int) -> None:
        row = self.table.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.table.rowCount():
            return
        tiers = self.tiers()
        tiers[row], tiers[target] = tiers[target], tiers[row]
        self._fill(tiers)
        self.table.selectRow(target)

    def _fill(self, tiers: list[TierDef]) -> None:
        self.table.setRowCount(0)
        for tier in tiers:
            self.add_tier(tier.name, tier.divisions)

    # --- load / read ------------------------------------------------------------------------

    def load(self, template: GameTemplate) -> None:
        """Show a template's ladder and division style."""
        self._fill(list(template.tiers))
        self.best_is_one.setChecked(template.best_division_is_one)
        self.roman.setChecked(template.roman_divisions)

    def tiers(self) -> list[TierDef]:
        """Current rows as TierDefs (blank names included; core validation rejects them)."""
        result = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            spin = self.table.cellWidget(row, 1)
            divisions = spin.value() if isinstance(spin, QSpinBox) else 0
            result.append(TierDef(item.text() if item else "", divisions))
        return result
