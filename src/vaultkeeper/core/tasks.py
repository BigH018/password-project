"""Task-runner interface for slow work (Argon2), plus an inline implementation.

The UI supplies a threaded implementation (``ui/qt_adapters.QtTaskRunner``). Core code only
depends on this protocol, so it stays headless and testable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, TypeVar

T = TypeVar("T")


class TaskRunner(Protocol):
    """Runs ``task`` (possibly on another thread) and delivers the result via callbacks.

    Callbacks must be invoked on the thread that owns the service (the UI thread).
    """

    def submit(
        self,
        task: Callable[[], T],
        on_success: Callable[[T], None],
        on_error: Callable[[BaseException], None],
    ) -> None: ...


class InlineTaskRunner:
    """Runs tasks immediately on the calling thread (tests, scripts)."""

    def submit(
        self,
        task: Callable[[], T],
        on_success: Callable[[T], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        try:
            result = task()
        except Exception as exc:  # every failure is delivered to the caller
            on_error(exc)
            return
        on_success(result)
