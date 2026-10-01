"""Branding: the app icon on every window and the taskbar, and the Windows taskbar identity."""

from __future__ import annotations

import logging
import sys
from importlib import resources

from PyQt5.QtCore import QBuffer, QByteArray, QCoreApplication, QIODevice, Qt
from PyQt5.QtGui import QIcon, QImageReader, QPixmap
from PyQt5.QtWidgets import QApplication

from vaultkeeper.config.constants import APP_USER_MODEL_ID

log = logging.getLogger(__name__)

ICON_NAME = "app_icon.ico"


def load_app_icon(name: str = ICON_NAME) -> QIcon:
    """Every size in the bundled .ico as one QIcon (empty if it can't be read)."""
    try:
        data = (resources.files("vaultkeeper.ui") / "assets" / name).read_bytes()
    except OSError as exc:
        log.warning("App icon unavailable (%s)", type(exc).__name__)
        return QIcon()
    raw = QByteArray(data)
    buffer = QBuffer(raw)
    buffer.open(QIODevice.ReadOnly)
    reader = QImageReader(buffer, b"ico")
    icon = QIcon()
    while True:
        image = reader.read()
        if not image.isNull():
            icon.addPixmap(QPixmap.fromImage(image))
        if not reader.jumpToNextImage():
            break
    if icon.isNull():
        log.warning("App icon could not be decoded")
    return icon


def set_windows_app_id(app_id: str = APP_USER_MODEL_ID) -> bool:
    """Give the process its own taskbar identity so Windows shows our icon, not Python's."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (OSError, AttributeError) as exc:
        log.warning("Taskbar identity not set (%s)", type(exc).__name__)
        return False
    return result == 0  # S_OK


def disable_help_buttons() -> None:
    """Drop the "?" title-bar button from every dialog (we have no context help).

    Call before the QApplication is created; dialogs made afterwards pick it up.
    """
    QCoreApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton)


def apply_branding(app: QApplication) -> None:
    """Set the taskbar identity and the window icon used by every window and dialog."""
    set_windows_app_id()
    app.setWindowIcon(load_app_icon())
