"""Generic "Something went wrong" notice for uncaught exceptions.

The exception hook (``config.logging_setup``) logs type + location only and then calls
``ErrorReporter.report()`` with no arguments, so this module never sees the exception or
its message. The app keeps running: every change is saved as it is made.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtCore import QObject, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import QMessageBox, QWidget

ERROR_TITLE = "Something went wrong"
ERROR_TEXT = (
    "Something unexpected went wrong. Your saved accounts are safe: every change is saved "
    "the moment you make it.\n\n"
    "You can keep working, but restarting the app is the safest choice."
)
LOG_NOTE = "Technical details (without any of your data) were written to the log in:\n{folder}"
OPEN_LOGS = "Open log folder"


def build_error_box(log_folder: Path | None, parent: QWidget | None = None) -> QMessageBox:
    """The notice itself (not shown). Has an "Open log folder" button when a folder is known."""
    box = QMessageBox(QMessageBox.Warning, ERROR_TITLE, ERROR_TEXT, QMessageBox.Ok, parent)
    if log_folder is not None:
        box.setInformativeText(LOG_NOTE.format(folder=log_folder))
        box.addButton(OPEN_LOGS, QMessageBox.ActionRole)
    box.setDefaultButton(QMessageBox.Ok)
    box.setStyleSheet("QLabel#qt_msgbox_label, QLabel#qt_msgbox_informativelabel "
                      "{ min-width: 440px; }")  # room for the log path (not the icon)
    return box


def open_folder(folder: Path) -> None:
    """Open a local folder in the file manager (a file:// URL: no network)."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


def show_error_box(log_folder: Path | None,
                   opener: Callable[[Path], None] = open_folder) -> None:
    """Show the notice modally; open the log folder if asked."""
    box = build_error_box(log_folder)
    box.exec_()
    clicked = box.clickedButton()
    if log_folder is not None and clicked is not None and clicked.text() == OPEN_LOGS:
        opener(log_folder)


class ErrorReporter(QObject):
    """Thread-safe trigger for the notice. Only one notice is open at a time."""

    _raised = pyqtSignal()

    def __init__(self, log_folder: Path | None,
                 show: Callable[[Path | None], None] = show_error_box) -> None:
        super().__init__()
        self._log_folder = log_folder
        self._show_box = show
        self.showing = False
        self.shown = 0
        # Queued: the box opens from the event loop, never inside the failing call or a
        # worker thread.
        self._raised.connect(self._show, Qt.QueuedConnection)

    def report(self) -> None:
        """Ask for the notice. Safe from any thread; repeats while one is open are dropped."""
        self._raised.emit()

    def _show(self) -> None:
        if self.showing:
            return
        self.showing = True
        self.shown += 1
        try:
            self._show_box(self._log_folder)
        finally:
            self.showing = False
