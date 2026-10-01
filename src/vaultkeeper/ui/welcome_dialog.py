"""First screen when no vault is configured: create a new one or open an existing file."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt5.QtWidgets import QDialog, QPushButton, QVBoxLayout, QWidget

from vaultkeeper.config.constants import DISPLAY_NAME, WINDOW_TITLE
from vaultkeeper.ui.file_pickers import choose_open_file
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import MUTED_STYLE

FileChooser = Callable[[QWidget], str]


def choose_vault_file(parent: QWidget) -> str:
    """Ask for an existing .vault file. Returns '' if cancelled."""
    return choose_open_file(parent, "Open a vault", "")


class WelcomeDialog(QDialog):
    """After ``exec_()``: ``choice`` is ``"create"``, ``"open"`` (with ``path``) or None."""

    def __init__(
        self, choose_file: FileChooser = choose_vault_file, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._choose_file = choose_file
        self.choice: str | None = None
        self.path: Path | None = None
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumWidth(420)

        intro = plain_label(
            f"{DISPLAY_NAME} keeps your game accounts in one encrypted file on this PC. "
            "Nothing is ever sent over the network.", self)
        intro.setWordWrap(True)
        intro.setStyleSheet(MUTED_STYLE)
        self.create_button = QPushButton("Create a new vault", self)
        self.create_button.setDefault(True)
        self.open_button = QPushButton("Open an existing vault...", self)
        self.quit_button = QPushButton("Quit", self)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.create_button)
        layout.addWidget(self.open_button)
        layout.addWidget(self.quit_button)

        self.create_button.clicked.connect(self._create)
        self.open_button.clicked.connect(self._open)
        self.quit_button.clicked.connect(self.reject)

    def _create(self) -> None:
        self.choice = "create"
        self.accept()

    def _open(self) -> None:
        chosen = self._choose_file(self)
        if chosen:
            self.choice = "open"
            self.path = Path(chosen)
            self.accept()
