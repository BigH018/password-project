"""Live master-password strength hint (score bar, label, suggestions)."""

from __future__ import annotations

from PyQt5.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from vaultkeeper.core.password_policy import strength_hint
from vaultkeeper.ui.theme import MUTED_STYLE


class StrengthMeter(QWidget):
    """Shows ``core.password_policy.strength_hint`` for the text it's given."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bar = QProgressBar(self)
        self.bar.setRange(0, 4)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.label = QLabel(self)
        self.suggestions = QLabel(self)
        self.suggestions.setWordWrap(True)
        self.suggestions.setStyleSheet(MUTED_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.bar)
        layout.addWidget(self.label)
        layout.addWidget(self.suggestions)
        self.update_for("")

    def update_for(self, password: str) -> None:
        """Recompute the hint. The password itself is never displayed or stored here."""
        hint = strength_hint(password)
        self.bar.setValue(hint.score)
        self.label.setText(f"Strength: {hint.label}" if password else "Strength: -")
        self.suggestions.setText("\n".join(hint.suggestions) if password else "")
