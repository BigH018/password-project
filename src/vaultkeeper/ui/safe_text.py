"""Labels and message boxes that never render text as HTML.

Qt's default (``Qt.AutoText``) renders anything that looks like HTML. An account named
``<img src=//host/x>`` would then try to load a remote image, which on Windows can open an
outbound SMB connection. Every label and message box in the UI is built here with
``Qt.PlainText``; ``tests/test_architecture.py`` enforces it.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QMessageBox, QWidget


def plain_label(text: str = "", parent: QWidget | None = None) -> QLabel:
    """A label that always shows ``text`` literally."""
    label = QLabel(parent)
    label.setTextFormat(Qt.PlainText)
    label.setText(text)
    return label


def link_label(text: str, parent: QWidget | None = None) -> QLabel:
    """A rich-text label for FIXED app text with an in-app link. Never pass user data.

    Links are reported through ``linkActivated``; nothing is ever opened externally.
    """
    label = QLabel(parent)
    label.setTextFormat(Qt.RichText)
    label.setOpenExternalLinks(False)
    label.setText(text)
    return label


def message_box(icon: QMessageBox.Icon, title: str, text: str,
                buttons: QMessageBox.StandardButtons | QMessageBox.StandardButton,
                parent: QWidget | None = None) -> QMessageBox:
    """A message box whose text is always shown literally."""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setTextFormat(Qt.PlainText)
    box.setText(text)
    box.setStandardButtons(buttons)
    return box


def set_informative_text(box: QMessageBox, text: str) -> None:
    """Set a message box's second line of text, also shown literally."""
    box.setInformativeText(text)
    label = box.findChild(QLabel, "qt_msgbox_informativelabel")
    if label is not None:
        label.setTextFormat(Qt.PlainText)
