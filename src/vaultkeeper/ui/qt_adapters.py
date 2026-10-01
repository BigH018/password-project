"""Qt implementations of core/security interfaces.

``QtClipboardBackend``/``qt_schedule`` feed ``security.clipboard.ClipboardGuard``;
``ActivityFilter`` and ``SessionLockWatcher`` feed auto-lock. ``QtTaskRunner`` runs slow
work (Argon2) on a background thread and delivers results on the UI thread through a queued
Qt signal.

It uses plain *daemon* threads on purpose. Qt's thread pool waits for running tasks when the
app quits, so a hung key derivation would make the app impossible to close. A daemon thread
is simply abandoned on exit. ``cancel_pending()`` discards results from work the user walked
away from (for example by closing the dialog).

``VaultInstanceLock`` stops two running copies of the app from opening the same vault.
``set_capture_excluded``/``CaptureFilter`` hide windows from screenshots and screen sharing
(Windows only, optional).
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

from PyQt5.QtCore import QEvent, QLockFile, QMimeData, QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QWidget

T = TypeVar("T")
log = logging.getLogger(__name__)


class _Relay(QObject):
    """Lives on the UI thread. Signals emitted from workers are queued onto it."""

    finished = pyqtSignal(int, bool, object)  # ticket, ok, result-or-exception


class QtTaskRunner:
    """TaskRunner for the UI: work on a daemon thread, callbacks on the UI thread."""

    def __init__(self) -> None:
        self._relay = _Relay()
        self._relay.finished.connect(self._deliver)
        self._pending: dict[int, tuple[Callable[[Any], None], Callable[[BaseException], None]]] = {}
        self._next_ticket = 0

    @property
    def busy(self) -> bool:
        """True while any non-cancelled task is running."""
        return bool(self._pending)

    def submit(
        self,
        task: Callable[[], T],
        on_success: Callable[[T], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        """Start ``task`` on a daemon thread; callbacks run on the UI thread later."""
        ticket = self._next_ticket
        self._next_ticket += 1
        self._pending[ticket] = (on_success, on_error)
        relay = self._relay

        def work() -> None:
            try:
                result: Any = task()
            except Exception as exc:  # delivered to on_error on the UI thread
                relay.finished.emit(ticket, False, exc)
                return
            relay.finished.emit(ticket, True, result)

        threading.Thread(target=work, name=f"vaultkeeper-task-{ticket}", daemon=True).start()

    def cancel_pending(self) -> None:
        """Forget all running tasks. Their results (or errors) are discarded on arrival."""
        self._pending.clear()

    def _deliver(self, ticket: int, ok: bool, payload: object) -> None:
        callbacks = self._pending.pop(ticket, None)
        if callbacks is None:
            return  # cancelled: discard
        on_success, on_error = callbacks
        if ok:
            on_success(payload)
        else:
            on_error(payload)  # type: ignore[arg-type]


# --- clipboard ------------------------------------------------------------------------------

# Windows clipboard formats that keep a copy out of Clipboard History (Win+V), cloud clipboard
# sync and clipboard monitors. Same approach as KeePassXC. Ignored on other platforms.
_EXCLUDE_FORMATS = {
    "ExcludeClipboardContentFromMonitorProcessing": b"\x01\x00\x00\x00",
    "CanIncludeInClipboardHistory": b"\x00\x00\x00\x00",
    "CanUploadToCloudClipboard": b"\x00\x00\x00\x00",
}


class QtClipboardBackend:
    """ClipboardBackend on top of QClipboard."""

    def __init__(self) -> None:
        self._clipboard = QApplication.clipboard()

    def set_text(self, text: str) -> None:
        """Copy text, marked as excluded from clipboard history/sync on Windows."""
        mime = QMimeData()
        mime.setText(text)
        if sys.platform == "win32":
            for name, value in _EXCLUDE_FORMATS.items():
                mime.setData(name, value)
        self._clipboard.setMimeData(mime)

    def text(self) -> str:
        """Current clipboard text."""
        return self._clipboard.text()

    def clear(self) -> None:
        """Empty the clipboard."""
        self._clipboard.clear()


class _QtTimerHandle:
    def __init__(self, seconds: float, fn: Callable[[], None]) -> None:
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(fn)
        self._timer.start(int(seconds * 1000))

    def cancel(self) -> None:
        self._timer.stop()


def qt_schedule(seconds: float, fn: Callable[[], None]) -> _QtTimerHandle:
    """Scheduler for ClipboardGuard: run ``fn`` once after ``seconds`` on the UI thread."""
    return _QtTimerHandle(seconds, fn)


# --- activity & session lock ----------------------------------------------------------------


class ActivityFilter(QObject):
    """App-wide event filter: reports key/mouse activity (for auto-lock)."""

    def __init__(self, on_activity: Callable[[], None]) -> None:
        super().__init__()
        self._on_activity = on_activity
        self._types = {QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseMove,
                       QEvent.Wheel}

    def eventFilter(self, _obj: QObject, event: Any) -> bool:  # noqa: N802 - Qt API
        if event.type() in self._types:
            self._on_activity()
        return False  # never swallow events


_WM_WTSSESSION_CHANGE = 0x02B1
_WTS_SESSION_LOCK = 0x7


class SessionLockWatcher:
    """Calls ``on_lock`` when Windows locks the workstation (Win+L, sleep, user switch).

    Uses WTSRegisterSessionNotification through ctypes (stdlib). Does nothing elsewhere.
    """

    def __init__(self, window_id: int, on_lock: Callable[[], None]) -> None:
        self._on_lock = on_lock
        self._filter: Any = None
        self.active = False
        if sys.platform != "win32":
            return
        try:
            import ctypes

            from PyQt5.QtCore import QAbstractNativeEventFilter, QCoreApplication

            wtsapi = ctypes.WinDLL("wtsapi32")
            if not wtsapi.WTSRegisterSessionNotification(ctypes.c_void_p(window_id), 0):
                return
            watcher = self

            class _Filter(QAbstractNativeEventFilter):
                def nativeEventFilter(self, event_type: Any, message: Any) -> Any:  # noqa: N802
                    if event_type == b"windows_generic_MSG":
                        from ctypes import wintypes

                        msg = wintypes.MSG.from_address(int(message))
                        if (msg.message == _WM_WTSSESSION_CHANGE
                                and msg.wParam == _WTS_SESSION_LOCK):
                            watcher._on_lock()
                    return False, 0

            self._filter = _Filter()
            QCoreApplication.instance().installNativeEventFilter(self._filter)
            self.active = True
        except (OSError, AttributeError):
            self.active = False  # unavailable: the other auto-lock triggers still apply


class VaultInstanceLock:
    """``<vault>.lock`` held while this copy of the app has the vault open (SEC-M2).

    A second running copy can't take it, so two copies never overwrite each other. A lock
    left by a crashed copy is taken over: with no age limit (``setStaleLockTime(0)``), Qt
    treats a lock as stale only when the process that holds it is gone.
    """

    def __init__(self) -> None:
        self._lock: QLockFile | None = None
        self._path: Path | None = None

    def acquire(self, vault: Path) -> bool:
        """Lock ``vault`` (releasing any other vault). False if another copy holds it."""
        if self._lock is not None and self._path == vault:
            return True
        self.release()
        lock = QLockFile(str(vault) + ".lock")
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            if lock.error() == QLockFile.LockFailedError:
                return False
            # The folder doesn't allow a lock file (e.g. read-only). Saving refuses to
            # overwrite changes made by another copy anyway (core/vault_disk.py).
            log.warning("Could not create the vault lock file (error %d)", int(lock.error()))
            return True
        self._lock, self._path = lock, vault
        return True

    def release(self) -> None:
        """Give the lock up (on quit or when switching to another vault)."""
        if self._lock is not None:
            self._lock.unlock()
        self._lock, self._path = None, None


WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004+; older Windows shows the window black


def set_capture_excluded(widget: QWidget, excluded: bool, *, platform: str = sys.platform,
                         user32: Any = None) -> bool:
    """Exclude a top-level window from screenshots and screen sharing (SEC-Low6).

    Windows only (SetWindowDisplayAffinity); a no-op returning False elsewhere.
    """
    if platform != "win32":
        return False
    try:
        if user32 is None:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.SetWindowDisplayAffinity.argtypes = (wintypes.HWND, wintypes.DWORD)
            user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        affinity = WDA_EXCLUDEFROMCAPTURE if excluded else WDA_NONE
        ok = user32.SetWindowDisplayAffinity(int(widget.winId()), affinity)
    except (OSError, AttributeError) as exc:
        log.warning("Screen-capture setting not applied (%s)", type(exc).__name__)
        return False
    return bool(ok)


class CaptureFilter(QObject):
    """App-wide: while enabled, every top-level window is excluded from screen capture."""

    def __init__(self) -> None:
        super().__init__()
        self.enabled = False

    def set_enabled(self, enabled: bool) -> None:
        """Switch on/off, applying it to the windows already open."""
        if enabled == self.enabled:
            return
        self.enabled = enabled
        for widget in QApplication.topLevelWidgets():
            if widget.isVisible():
                set_capture_excluded(widget, enabled)

    def eventFilter(self, obj: QObject, event: Any) -> bool:  # noqa: N802 - Qt API
        if (self.enabled and event.type() == QEvent.Show and isinstance(obj, QWidget)
                and obj.isWindow()):
            set_capture_excluded(obj, True)
        return False
