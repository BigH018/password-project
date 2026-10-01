"""Interim look: Qt's Fusion style with a dark palette (the full QSS theme comes in Phase 8)."""

from __future__ import annotations

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

_COLORS = {
    QPalette.Window: "#1f2227",
    QPalette.WindowText: "#e6e6e6",
    QPalette.Base: "#16181c",
    QPalette.AlternateBase: "#22252b",
    QPalette.ToolTipBase: "#2b2f36",
    QPalette.ToolTipText: "#e6e6e6",
    QPalette.Text: "#e6e6e6",
    QPalette.Button: "#2b2f36",
    QPalette.ButtonText: "#e6e6e6",
    QPalette.BrightText: "#ff5c5c",
    QPalette.Highlight: "#3d7eff",
    QPalette.HighlightedText: "#ffffff",
    QPalette.Link: "#6ea0ff",
    QPalette.PlaceholderText: "#8a8f98",
}
_DISABLED = {
    QPalette.WindowText: "#6b7079",
    QPalette.Text: "#6b7079",
    QPalette.ButtonText: "#6b7079",
}

ERROR_STYLE = "color: #ff7b7b;"
WARNING_BANNER_STYLE = (
    "background: #5a4a12; color: #ffe08a; padding: 8px; border-radius: 4px;"
)
MUTED_STYLE = "color: #9aa0a8;"


def apply_dark_theme(app: QApplication) -> None:
    """Switch the application to Fusion with a dark palette."""
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in _COLORS.items():
        palette.setColor(role, QColor(color))
    for role, color in _DISABLED.items():
        palette.setColor(QPalette.Disabled, role, QColor(color))
    app.setPalette(palette)
