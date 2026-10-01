"""Clipboard auto-clear and auto-lock wiring for the running app.

Emits ``lock_needed(reason)`` when the vault should lock: inactivity, the window being
minimized, or Windows locking the session. The controller decides what locking means.
"""

from __future__ import annotations

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

from vaultkeeper.config.settings import Settings
from vaultkeeper.security.autolock import InactivityTracker
from vaultkeeper.security.clipboard import ClipboardBackend, ClipboardGuard, Scheduler
from vaultkeeper.ui.qt_adapters import (
    ActivityFilter,
    QtClipboardBackend,
    SessionLockWatcher,
    qt_schedule,
)

CHECK_INTERVAL_MS = 1000


class SessionGuard(QObject):
    """Owns the ClipboardGuard and the auto-lock machinery."""

    lock_needed = pyqtSignal(str)  # reason: "inactivity" | "minimized" | "session"

    def __init__(self, settings: Settings, backend: ClipboardBackend | None = None,
                 schedule: Scheduler = qt_schedule) -> None:
        super().__init__()
        self._settings = settings
        self.clipboard = ClipboardGuard(backend or QtClipboardBackend(), schedule,
                                        settings.clipboard_clear_seconds)
        self.tracker = InactivityTracker(settings.autolock_minutes * 60)
        self.armed = False  # only lock while unlocked
        self._filter = ActivityFilter(self.tracker.record_activity)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self._filter)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._check)
        self._timer.start(CHECK_INTERVAL_MS)
        self._session_watcher: SessionLockWatcher | None = None

    def apply_settings(self, settings: Settings) -> None:
        """Pick up changed timeouts / switches."""
        self._settings = settings
        self.clipboard.clear_after = settings.clipboard_clear_seconds
        self.tracker.set_base_timeout(settings.autolock_minutes * 60)

    def watch_session(self, window_id: int) -> bool:
        """Lock when Windows locks (if enabled). Returns True if the watcher is active."""
        if self._settings.lock_on_session_lock and self._session_watcher is None:
            self._session_watcher = SessionLockWatcher(window_id, self._session_locked)
        return bool(self._session_watcher and self._session_watcher.active)

    def arm(self) -> None:
        """Vault unlocked: start counting inactivity from now."""
        self.tracker.record_activity()
        self.armed = True

    def disarm(self) -> None:
        """Vault locked: nothing to auto-lock; clear our clipboard copy."""
        self.armed = False
        self.clipboard.clear_now()

    def window_minimized(self) -> None:
        """Called by the main window when it is minimized."""
        if self.armed and self._settings.lock_on_minimize:
            self.lock_needed.emit("minimized")

    def _session_locked(self) -> None:
        if self.armed:
            self.lock_needed.emit("session")

    def _check(self) -> None:
        if self.armed and self.tracker.should_lock():
            self.lock_needed.emit("inactivity")
