"""Rank list editor: tiers in order (lowest first), divisions, pictures, division style."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QSize, Qt
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
from vaultkeeper.core.rank_image import MAX_SIDE
from vaultkeeper.ui.messages import run_modal
from vaultkeeper.ui.rank_pictures import PicturePicker, picture_icon, picture_pixmap
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import MUTED_STYLE
from vaultkeeper.ui.widgets.add_rank_dialog import AddRankDialog

IMAGE_ROLE = Qt.UserRole + 1  # the rank's picture (PNG bytes or None), on the name cell
ROW_HEIGHT = 34
ICON_SIZE = 28
PREVIEW_STYLE = "border: 1px solid #3a3f47; border-radius: 4px; background: #16181c;"


class LadderEditor(QWidget):
    """Tall table of ranks (with pictures) + divisions; actions and a preview on the right."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.pictures = PicturePicker()
        self.table = QTableWidget(0, 2, self)
        self.table.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.table.setHorizontalHeaderLabels(["Rank (lowest first)", "Divisions"])
        self.table.horizontalHeaderItem(1).setToolTip("0 = this rank has no divisions")
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.resizeSection(1, 110)
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.add_button = QPushButton("Add ranks...", self)
        self.remove_button = QPushButton("Remove", self)
        self.up_button = QPushButton("Move up", self)
        self.down_button = QPushButton("Move down", self)
        self.picture_button = QPushButton("Set picture...", self)
        self.picture_button.setToolTip("Choose an .ico or .png picture for the selected rank")
        self.remove_picture_button = QPushButton("Remove picture", self)
        self.preview = plain_label(parent=self)
        self.preview.setFixedSize(MAX_SIDE + 16, MAX_SIDE + 16)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(PREVIEW_STYLE)
        self.best_is_one = QCheckBox("Division 1 is the best (like Overwatch)", self)
        self.roman = QCheckBox("Show divisions as I, II, III", self)
        self._build_layout()

        self.add_button.clicked.connect(self.open_add_dialog)
        self.remove_button.clicked.connect(self._remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.picture_button.clicked.connect(self._choose_picture)
        self.remove_picture_button.clicked.connect(lambda: self._set_picture(None))
        self.table.currentCellChanged.connect(self._selection_changed)
        self._selection_changed()

    def _build_layout(self) -> None:
        side = QVBoxLayout()
        for button in (self.add_button, self.remove_button, self.up_button, self.down_button):
            side.addWidget(button)
        side.addSpacing(16)
        picture_title = plain_label("Picture", self)
        picture_title.setStyleSheet(MUTED_STYLE)
        side.addWidget(picture_title)
        side.addWidget(self.preview, 0, Qt.AlignHCenter)
        side.addWidget(self.picture_button)
        side.addWidget(self.remove_picture_button)
        side.addStretch(1)
        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        body.addLayout(side)
        options = QHBoxLayout()
        options.addWidget(self.best_is_one)
        options.addSpacing(24)
        options.addWidget(self.roman)
        options.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addLayout(options)

    def _selection_changed(self, *_args: Any) -> None:
        """Show the selected rank's picture; rank actions need a selected rank."""
        item = self.table.item(self.table.currentRow(), 0)
        image = item.data(IMAGE_ROLE) if item is not None else None
        self.preview.setPixmap(picture_pixmap(image if isinstance(image, bytes) else None))
        if item is not None and not isinstance(image, bytes):
            self.preview.setText("none")
        for button in (self.remove_button, self.up_button, self.down_button,
                       self.picture_button):
            button.setEnabled(item is not None)
        self.remove_picture_button.setEnabled(isinstance(image, bytes))

    # --- rows -------------------------------------------------------------------------------

    def add_tier(self, name: str, divisions: int, image: bytes | None = None,
                 edit: bool = False) -> None:
        """Append a tier row (optionally start editing its name)."""
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(name)
        item.setData(IMAGE_ROLE, image)
        item.setIcon(picture_icon(image))
        self.table.setItem(row, 0, item)
        spin = QSpinBox(self.table)
        spin.setRange(0, MAX_DIVISIONS)
        spin.setValue(divisions)
        spin.setSpecialValueText("none")
        self.table.setCellWidget(row, 1, spin)
        self.table.selectRow(row)
        if edit:
            self.table.editItem(self.table.item(row, 0))

    def open_add_dialog(self) -> AddRankDialog:
        """Open the quick add form (name + divisions yes/no + how many)."""
        dialog = AddRankDialog(self.add_tier, [t.name for t in self.tiers()], self.pictures,
                               self)
        run_modal(dialog)
        return dialog

    def _choose_picture(self) -> None:
        if self.table.currentRow() < 0:
            return
        image = self.pictures.choose(self)
        if image is not None:
            self._set_picture(image)

    def _set_picture(self, image: bytes | None) -> None:
        item = self.table.item(self.table.currentRow(), 0)
        if item is not None:
            item.setData(IMAGE_ROLE, image)
            item.setIcon(picture_icon(image))
        self._selection_changed()

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
            self.add_tier(tier.name, tier.divisions, tier.image)

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
            image = item.data(IMAGE_ROLE) if item else None
            result.append(TierDef(item.text() if item else "", divisions,
                                  image if isinstance(image, bytes) else None))
        return result
