"""Rank (tier + division) and region pickers driven by a game's preset.

Fixed-ladder presets get dropdowns, so ranks are never typed. Free-text presets (custom
games) get a text box. A stored value no longer in the preset (e.g. a renamed tier) is still
shown, marked, so editing never silently drops it.
"""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QStackedWidget, QWidget

from vaultkeeper.config.constants import UNRANKED_LABEL, GamePreset, format_division
from vaultkeeper.core.models import Rank

NOT_IN_LIST = " (not in this game's list)"


class RankPicker(QWidget):
    """Tier dropdown + division dropdown, or a single text box for free-text presets."""

    changed = pyqtSignal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._preset: GamePreset | None = None
        self.tier = QComboBox(self)
        self.division = QComboBox(self)
        self.free = QLineEdit(self)
        self.free.setPlaceholderText("Rank, e.g. Diamond IV (optional)")
        combos = QWidget(self)
        row = QHBoxLayout(combos)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.tier, 2)
        row.addWidget(self.division, 1)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(combos)
        self.stack.addWidget(self.free)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.tier.currentIndexChanged.connect(self._tier_changed)
        self.division.currentIndexChanged.connect(self.changed)
        self.free.textChanged.connect(self.changed)

    @property
    def free_text(self) -> bool:
        """Whether the current preset uses a typed rank."""
        return self._preset is not None and self._preset.free_text

    def set_preset(self, preset: GamePreset, keep: Rank | None = None) -> None:
        """Switch ladders. ``keep`` is shown if possible (default: the current rank)."""
        keep = self.rank() if keep is None else keep
        self._preset = preset
        self.stack.setCurrentIndex(1 if preset.free_text else 0)
        if preset.free_text:
            self.free.setText(keep.tier or "")
            return
        self.tier.blockSignals(True)
        self.tier.clear()
        self.tier.addItem(UNRANKED_LABEL, None)
        for name in preset.tier_names:
            self.tier.addItem(name, name)
        if keep.tier is not None and preset.tier(keep.tier) is None:
            self.tier.addItem(keep.tier + NOT_IN_LIST, keep.tier)
        self.tier.setCurrentIndex(max(self.tier.findData(keep.tier), 0))
        self.tier.blockSignals(False)
        self._fill_divisions(keep.division)
        self.changed.emit()

    def set_rank(self, rank: Rank) -> None:
        """Show ``rank`` in the current preset."""
        if self._preset is not None:
            self.set_preset(self._preset, keep=rank)

    def rank(self) -> Rank:
        """The chosen rank (validated later by core)."""
        if self._preset is None:
            return Rank()
        if self._preset.free_text:
            return Rank(self.free.text().strip() or None, None)
        return Rank(self.tier.currentData(), self.division.currentData())

    def _tier_changed(self) -> None:
        self._fill_divisions(self.division.currentData())
        self.changed.emit()

    def _fill_divisions(self, keep: int | None) -> None:
        self.division.blockSignals(True)
        self.division.clear()
        self.division.addItem("-", None)
        tier = self.tier.currentData()
        spec = self._preset.tier(tier) if (self._preset and tier) else None
        if spec is not None and self._preset is not None:
            for number in reversed(spec.divisions):  # highest first, like the games show it
                self.division.addItem(format_division(self._preset, number), number)
        self.division.setEnabled(spec is not None and spec.has_divisions)
        self.division.setCurrentIndex(max(self.division.findData(keep), 0))
        self.division.blockSignals(False)


class RegionPicker(QWidget):
    """Region dropdown for fixed presets, text box for free-text presets."""

    changed = pyqtSignal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._preset: GamePreset | None = None
        self.combo = QComboBox(self)
        self.free = QLineEdit(self)
        self.free.setPlaceholderText("Region / server (optional)")
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.combo)
        self.stack.addWidget(self.free)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)
        self.combo.currentIndexChanged.connect(self.changed)
        self.free.textChanged.connect(self.changed)

    def set_preset(self, preset: GamePreset, keep: str | None = None,
                   use_current: bool = True) -> None:
        """Switch region lists, keeping ``keep`` (default: the current value) if possible."""
        if use_current and keep is None:
            keep = self.region()
        self._preset = preset
        self.stack.setCurrentIndex(1 if preset.free_text else 0)
        if preset.free_text:
            self.free.setText(keep or "")
            return
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("(none)", None)
        for region in preset.regions:
            self.combo.addItem(region, region)
        if keep and keep not in preset.regions:
            self.combo.addItem(keep + NOT_IN_LIST, keep)
        self.combo.setCurrentIndex(max(self.combo.findData(keep), 0))
        self.combo.blockSignals(False)
        self.changed.emit()

    def set_region(self, region: str | None) -> None:
        """Show ``region`` in the current preset."""
        if self._preset is not None:
            self.set_preset(self._preset, keep=region, use_current=False)

    def region(self) -> str | None:
        """The chosen region, or None."""
        if self._preset is None:
            return None
        if self._preset.free_text:
            return self.free.text().strip() or None
        return self.combo.currentData()
