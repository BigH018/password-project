"""Settings: auto-lock timeouts, clipboard clearing, lock switches, and a way to Backups.

Thin: the dialog only collects values. Ranges come from ``config.constants`` and the
controller validates, saves and applies them (``config.settings``, ``SessionGuard``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.config import constants as c
from vaultkeeper.config.settings import Settings
from vaultkeeper.ui.theme import MUTED_STYLE

# The settings this dialog edits (backup settings live in the Backups dialog).
EDITED_FIELDS = (
    "autolock_minutes",
    "quick_add_autolock_minutes",
    "clipboard_clear_seconds",
    "lock_on_minimize",
    "lock_on_session_lock",
)


def _spin(value_range: tuple[int, int], value: int, suffix: str, parent: QWidget) -> QSpinBox:
    spin = QSpinBox(parent)
    spin.setRange(*value_range)
    spin.setValue(value)
    spin.setSuffix(suffix)
    return spin


class SettingsDialog(QDialog):
    """Accepting leaves the chosen values in ``values()``; Cancel changes nothing."""

    def __init__(self, settings: Settings, open_backups: Callable[[], None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._open_backups = open_backups
        self.setWindowTitle("Settings")
        self.setMinimumWidth(440)

        self.autolock_spin = _spin(c.AUTOLOCK_MINUTES_RANGE, settings.autolock_minutes,
                                   " min", self)
        self.quick_add_spin = _spin(c.AUTOLOCK_MINUTES_RANGE,
                                    settings.quick_add_autolock_minutes, " min", self)
        self.clipboard_spin = _spin(c.CLIPBOARD_CLEAR_SECONDS_RANGE,
                                    settings.clipboard_clear_seconds, " s", self)
        self.minimize_check = QCheckBox("Lock when the window is minimized", self)
        self.minimize_check.setChecked(settings.lock_on_minimize)
        self.session_check = QCheckBox("Lock when Windows locks (Win+L, sleep, switch user)",
                                       self)
        self.session_check.setChecked(settings.lock_on_session_lock)
        note = QLabel("Locking clears the window and any password still on the clipboard.", self)
        note.setWordWrap(True)
        note.setStyleSheet(MUTED_STYLE)

        self.backups_button = QPushButton("Backups...", self)
        self.backups_button.setEnabled(open_backups is not None)
        self.defaults_button = QPushButton("Restore defaults", self)
        self.save_button = QPushButton("Save", self)
        self.save_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel", self)

        form = QFormLayout()
        form.addRow("Auto-lock after", self.autolock_spin)
        form.addRow("While Quick Add is open", self.quick_add_spin)
        form.addRow("Clear copied passwords after", self.clipboard_spin)
        buttons = QHBoxLayout()
        buttons.addWidget(self.backups_button)
        buttons.addWidget(self.defaults_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.minimize_check)
        layout.addWidget(self.session_check)
        layout.addWidget(note)
        layout.addLayout(buttons)

        self.backups_button.clicked.connect(self._backups)
        self.defaults_button.clicked.connect(self.restore_defaults)
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def values(self) -> dict[str, Any]:
        """The edited settings, keyed by ``Settings`` field name."""
        return {
            "autolock_minutes": self.autolock_spin.value(),
            "quick_add_autolock_minutes": self.quick_add_spin.value(),
            "clipboard_clear_seconds": self.clipboard_spin.value(),
            "lock_on_minimize": self.minimize_check.isChecked(),
            "lock_on_session_lock": self.session_check.isChecked(),
        }

    def restore_defaults(self) -> None:
        """Put the default values in the form (nothing is saved until Save)."""
        d = Settings()
        self.autolock_spin.setValue(d.autolock_minutes)
        self.quick_add_spin.setValue(d.quick_add_autolock_minutes)
        self.clipboard_spin.setValue(d.clipboard_clear_seconds)
        self.minimize_check.setChecked(d.lock_on_minimize)
        self.session_check.setChecked(d.lock_on_session_lock)

    def _backups(self) -> None:
        if self._open_backups is not None:
            self._open_backups()
