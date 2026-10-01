"""Main window shell (4a): menus, backup banner, status bar. Accounts arrive in 4b."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import QAction, QLabel, QMainWindow, QVBoxLayout, QWidget

from vaultkeeper.config.constants import APP_NAME
from vaultkeeper.ui.theme import MUTED_STYLE, WARNING_BANNER_STYLE

BACKUP_BANNER = (
    "Opened from the backup copy. When you next save, the damaged vault file will be kept "
    "aside as a separate '.damaged' file and replaced. The backup copy itself is not touched."
)


class MainWindow(QMainWindow):
    """Top-level window. Emits ``lock_requested``; the controller does the locking."""

    lock_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, demo: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} - DEMO (fake data)" if demo else APP_NAME)
        self.resize(1100, 700)

        self.banner = QLabel(BACKUP_BANNER, self)
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(WARNING_BANNER_STYLE)
        self.banner.hide()
        self.placeholder = QLabel(self)
        self.placeholder.setAlignment(Qt.AlignCenter)
        self.placeholder.setStyleSheet(MUTED_STYLE)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(self.placeholder, 1)
        self.setCentralWidget(central)

        self.lock_action = QAction("&Lock", self)
        self.lock_action.setShortcut(QKeySequence("Ctrl+L"))
        self.lock_action.triggered.connect(self.lock_requested)
        self.change_password_action = QAction("Change master password...", self)
        self.change_password_action.setEnabled(False)  # wired up in 4b
        self.quit_action = QAction("&Quit", self)
        self.quit_action.setShortcut(QKeySequence("Ctrl+Q"))
        self.quit_action.triggered.connect(self.quit_requested)
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self.lock_action)
        file_menu.addAction(self.change_password_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        self.show_locked()

    def show_locked(self) -> None:
        """Locked state: nothing decrypted is shown."""
        self.banner.hide()
        self.lock_action.setEnabled(False)
        self.placeholder.setText("Locked")
        self.statusBar().showMessage("Locked")

    def show_unlocked(self, vault_path: str, opened_from_backup: bool) -> None:
        """Unlocked state (4a shell: accounts table arrives in 4b)."""
        self.banner.setVisible(opened_from_backup)
        self.lock_action.setEnabled(True)
        self.placeholder.setText("Unlocked. The accounts view arrives in the next build (4b).")
        self.statusBar().showMessage(f"Vault: {vault_path}")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Closing the window quits the app (the controller locks first)."""
        self.quit_requested.emit()
        event.accept()
