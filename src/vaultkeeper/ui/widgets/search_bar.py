"""Free-text search plus status / rank / region / tag dropdowns. Builds an AccountFilter."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QPushButton, QWidget

from vaultkeeper.config.constants import STATUSES, UNRANKED_LABEL
from vaultkeeper.core.search import UNRANKED, AccountFilter, Facets

_ANY = None
_UNRANKED_KEY = "__unranked__"


def _combo(label: str, parent: QWidget) -> QComboBox:
    box = QComboBox(parent)
    box.addItem(f"{label}: any", _ANY)
    box.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    return box


def _refill(box: QComboBox, label: str, values: list[tuple[str, Any]],
            icons: dict[str, QIcon] | None = None) -> None:
    """Replace options (with ``icons`` by text), keeping the current choice if offered."""
    keep = box.currentData()
    box.blockSignals(True)
    box.clear()
    box.addItem(f"{label}: any", _ANY)
    for text, data in values:
        box.addItem((icons or {}).get(text, QIcon()), text, data)
    index = box.findData(keep) if keep is not None else 0
    box.setCurrentIndex(max(index, 0))
    box.blockSignals(False)


class SearchBar(QWidget):
    """Emits ``changed`` whenever the text or any dropdown changes."""

    changed = pyqtSignal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.text = QLineEdit(self)
        self.text.setPlaceholderText("Search name, tag, login, email, notes, labels...")
        self.text.setClearButtonEnabled(True)
        self.status = _combo("Status", self)
        for status in STATUSES:
            self.status.addItem(status.capitalize(), status)
        self.rank = _combo("Rank", self)
        self.region = _combo("Region", self)
        self.tag = _combo("Label", self)
        self.clear_button = QPushButton("Clear", self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text, 1)
        for widget in (self.status, self.rank, self.region, self.tag, self.clear_button):
            layout.addWidget(widget)

        self.text.textChanged.connect(self.changed)
        for box in (self.status, self.rank, self.region, self.tag):
            box.currentIndexChanged.connect(self.changed)
        self.clear_button.clicked.connect(self.reset)

    def set_facets(self, facets: Facets, rank_icons: dict[str, QIcon] | None = None) -> None:
        """Offer the given tiers, regions and labels (keeps current choices if possible).

        ``rank_icons`` (rank name -> picture) is given only when one game is selected.
        """
        _refill(self.rank, "Rank",
                [(UNRANKED_LABEL, _UNRANKED_KEY), *((t, t) for t in facets.tiers)], rank_icons)
        _refill(self.region, "Region", [(r, r) for r in facets.regions])
        _refill(self.tag, "Label", [(t, t) for t in facets.tags])

    def build_filter(self, game_id: str | None) -> AccountFilter:
        """The current criteria as an AccountFilter."""
        def one(box: QComboBox) -> frozenset[Any]:
            data = box.currentData()
            return frozenset() if data is _ANY else frozenset({data})

        rank = self.rank.currentData()
        tiers: frozenset[str | None] = (
            frozenset() if rank is _ANY
            else frozenset({UNRANKED}) if rank == _UNRANKED_KEY
            else frozenset({rank})
        )  # fmt: skip
        return AccountFilter(
            game_id=game_id,
            statuses=one(self.status),
            tiers=tiers,
            regions=one(self.region),
            tags=one(self.tag),
            text=self.text.text(),
        )

    def reset(self) -> None:
        """Clear the text and set every dropdown back to "any"."""
        for box in (self.status, self.rank, self.region, self.tag):
            box.blockSignals(True)
            box.setCurrentIndex(0)
            box.blockSignals(False)
        self.text.blockSignals(True)
        self.text.clear()
        self.text.blockSignals(False)
        self.changed.emit()
