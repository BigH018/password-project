"""Dark look: Fusion style + dark palette, with the ``styles/dark.qss`` stylesheet on top.

The palette alone already gives a usable dark UI, so a missing or unreadable stylesheet
only costs polish: it is logged (no paths or user data) and the app carries on.
"""

from __future__ import annotations

import logging
from importlib import resources

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

log = logging.getLogger(__name__)

STYLESHEET_NAME = "dark.qss"

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


def load_stylesheet(name: str = STYLESHEET_NAME) -> str | None:
    """Return the bundled stylesheet text, or None if it can't be read."""
    try:
        return (resources.files("vaultkeeper.ui") / "styles" / name).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning("Stylesheet unavailable (%s); using the plain dark palette",
                    type(exc).__name__)
        return None


def apply_dark_theme(app: QApplication, stylesheet: str | None = None) -> bool:
    """Switch the application to Fusion, the dark palette and the dark stylesheet.

    ``stylesheet`` overrides the bundled file (tests). Returns True if a stylesheet was applied.
    """
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in _COLORS.items():
        palette.setColor(role, QColor(color))
    for role, color in _DISABLED.items():
        palette.setColor(QPalette.Disabled, role, QColor(color))
    app.setPalette(palette)
    qss = load_stylesheet() if stylesheet is None else stylesheet
    if qss:
        app.setStyleSheet(qss)
    return bool(qss)
