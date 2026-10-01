"""InactivityTracker: timeout, activity resets, Quick Add override, disable."""

from __future__ import annotations

from vaultkeeper.security.autolock import InactivityTracker


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_locks_after_timeout() -> None:
    clock = Clock()
    tracker = InactivityTracker(300, clock)
    clock.now += 299
    assert not tracker.should_lock()
    clock.now += 1
    assert tracker.should_lock()


def test_activity_resets_countdown() -> None:
    clock = Clock()
    tracker = InactivityTracker(300, clock)
    clock.now += 250
    tracker.record_activity()
    clock.now += 250
    assert not tracker.should_lock() and tracker.seconds_idle() == 250


def test_quick_add_override_and_restore() -> None:
    clock = Clock()
    tracker = InactivityTracker(300, clock)
    tracker.push_override(900)
    assert tracker.timeout == 900
    clock.now += 600
    assert not tracker.should_lock()
    tracker.pop_override()
    assert tracker.timeout == 300 and not tracker.should_lock()  # pop counts as activity
    tracker.pop_override()  # extra pop is harmless
    assert tracker.timeout == 300


def test_disable_and_base_timeout_change() -> None:
    clock = Clock()
    tracker = InactivityTracker(300, clock)
    tracker.enabled = False
    clock.now += 10_000
    assert not tracker.should_lock()
    tracker.enabled = True
    tracker.set_base_timeout(20_000)
    assert not tracker.should_lock()
