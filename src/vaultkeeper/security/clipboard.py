"""Copy to the clipboard and clear it again after a delay, but only if it still holds our copy.

Headless: the real clipboard and timer are injected (``ui/qt_adapters.py`` provides Qt
versions). Copied text is never logged.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from typing import Protocol

log = logging.getLogger(__name__)


class ClipboardBackend(Protocol):
    """Minimal clipboard access."""

    def set_text(self, text: str) -> None:
        """Put text on the clipboard (excluded from clipboard history where supported)."""

    def text(self) -> str:
        """Current clipboard text ("" if none)."""

    def clear(self) -> None:
        """Empty the clipboard."""


class Cancellable(Protocol):
    """A pending timer that can be cancelled."""

    def cancel(self) -> None: ...


Scheduler = Callable[[float, Callable[[], None]], Cancellable]


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class ClipboardGuard:
    """Copies text and clears the clipboard after ``clear_after`` seconds if unchanged."""

    def __init__(self, backend: ClipboardBackend, schedule: Scheduler,
                 clear_after: float = 15.0) -> None:
        self._backend = backend
        self._schedule = schedule
        self.clear_after = clear_after
        self._copied: str | None = None
        self._pending: Cancellable | None = None

    def copy(self, text: str) -> None:
        """Copy ``text`` and (re)start the auto-clear timer."""
        self._cancel_timer()
        self._backend.set_text(text)
        self._copied = text
        self._pending = self._schedule(self.clear_after, self._timer_fired)
        log.info("Copied to clipboard; auto-clear scheduled")

    def clear_now(self) -> bool:
        """Clear immediately if the clipboard still holds our copy (used on lock/quit).

        Returns True if it was cleared. Something the user copied since is left alone.
        """
        self._cancel_timer()
        copied, self._copied = self._copied, None
        if copied is None:
            return False
        if _same(self._backend.text(), copied):
            self._backend.clear()
            log.info("Clipboard cleared")
            return True
        return False

    def _timer_fired(self) -> None:
        self._pending = None
        self.clear_now()

    def _cancel_timer(self) -> None:
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None
