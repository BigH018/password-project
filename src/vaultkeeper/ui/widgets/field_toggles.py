"""Game setup switches for which optional standard fields a game shows."""

from __future__ import annotations

from typing import Any

from PyQt5.QtWidgets import QCheckBox, QGridLayout, QWidget

from vaultkeeper.core.game_template import OPTIONAL_FIELDS, GameTemplate
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import MUTED_STYLE

FIELD_LABELS = {
    "tag": "Tag (#)", "region": "Region", "rank": "Rank", "email_password": "Email password",
    "email_login_url": "Email login URL", "recovery_email": "Recovery email",
}  # fmt: skip
COLUMNS = 2


class FieldToggles(QWidget):
    """One checkbox per optional field (``boxes``, keyed by field name), in a grid."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.boxes = {key: QCheckBox(label, self) for key, label in FIELD_LABELS.items()}
        grid = QGridLayout(self)
        for i, box in enumerate(self.boxes.values()):
            grid.addWidget(box, i // COLUMNS, i % COLUMNS)
        always = plain_label(
            "Always shown: name, login, password, email, status, labels, notes.", self)
        always.setStyleSheet(MUTED_STYLE)
        always.setWordWrap(True)
        rows = -(-len(self.boxes) // COLUMNS)  # rounded up
        grid.addWidget(always, rows, 0, 1, COLUMNS)
        grid.setRowStretch(rows + 1, 1)  # spare height goes below, not between rows

    def load(self, template: GameTemplate) -> None:
        """Tick the fields the template shows."""
        for key, box in self.boxes.items():
            box.setChecked(template.shows(key))

    def hidden(self) -> frozenset[str]:
        """The optional fields that are switched off."""
        return frozenset(k for k in OPTIONAL_FIELDS if not self.boxes[k].isChecked())
