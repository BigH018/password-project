"""Inactivity tracking for auto-lock. Headless: the clock is injected.

The UI feeds it activity (key/mouse events) and asks ``should_lock()`` on a timer. Quick Add
pushes a longer timeout while it is open (you work from another window then).
"""

from __future__ import annotations

import time
from collections.abc import Callable


class InactivityTracker:
    """Decides when the vault should auto-lock."""

    def __init__(self, timeout_seconds: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._base_timeout = timeout_seconds
        self._overrides: list[float] = []
        self._last_activity = clock()

    @property
    def timeout(self) -> float:
        """Current timeout in seconds (the most recent override, if any)."""
        return self._overrides[-1] if self._overrides else self._base_timeout

    def set_base_timeout(self, seconds: float) -> None:
        """Change the normal timeout (from settings)."""
        self._base_timeout = seconds

    def push_override(self, seconds: float) -> None:
        """Use a different timeout until ``pop_override`` (e.g. while Quick Add is open)."""
        self._overrides.append(seconds)
        self.record_activity()

    def pop_override(self) -> None:
        """Undo the most recent ``push_override``."""
        if self._overrides:
            self._overrides.pop()
        self.record_activity()

    def record_activity(self) -> None:
        """The user did something: restart the countdown."""
        self._last_activity = self._clock()

    def seconds_idle(self) -> float:
        """Seconds since the last recorded activity."""
        return self._clock() - self._last_activity

    def should_lock(self) -> bool:
        """True once the user has been idle for at least the current timeout."""
        return self.seconds_idle() >= self.timeout
