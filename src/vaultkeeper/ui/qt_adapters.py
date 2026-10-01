"""Qt implementations of core interfaces.

``QtTaskRunner`` runs slow work (Argon2) on a background thread and delivers results on the
UI thread through a queued Qt signal.

It uses plain *daemon* threads on purpose. Qt's thread pool waits for running tasks when the
app quits, so a hung key derivation would make the app impossible to close. A daemon thread
is simply abandoned on exit. ``cancel_pending()`` discards results from work the user walked
away from (for example by closing the dialog).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar

from PyQt5.QtCore import QObject, pyqtSignal

T = TypeVar("T")


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
