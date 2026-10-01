"""ClipboardGuard: clears after the delay only if unchanged; re-copy restarts; clear on lock."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from vaultkeeper.security.clipboard import ClipboardGuard


class FakeClipboard:
    def __init__(self) -> None:
        self.value = ""
        self.clears = 0

    def set_text(self, text: str) -> None:
        self.value = text

    def text(self) -> str:
        return self.value

    def clear(self) -> None:
        self.value = ""
        self.clears += 1


class FakeTimer:
    def __init__(self, seconds: float, fn: Callable[[], None]) -> None:
        self.seconds, self.fn, self.cancelled = seconds, fn, False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.fn()


@pytest.fixture
def setup() -> tuple[ClipboardGuard, FakeClipboard, list[FakeTimer]]:
    board, timers = FakeClipboard(), []

    def schedule(seconds: float, fn: Callable[[], None]) -> FakeTimer:
        timer = FakeTimer(seconds, fn)
        timers.append(timer)
        return timer

    return ClipboardGuard(board, schedule, clear_after=15), board, timers


def test_copy_then_auto_clear(setup: tuple[ClipboardGuard, FakeClipboard, list[FakeTimer]]
                              ) -> None:
    guard, board, timers = setup
    guard.copy("Fake-Passw0rd-1!")
    assert board.value == "Fake-Passw0rd-1!" and timers[0].seconds == 15
    timers[0].fire()
    assert board.value == ""


def test_does_not_clear_something_else(setup: tuple[ClipboardGuard, FakeClipboard,
                                                    list[FakeTimer]]) -> None:
    guard, board, timers = setup
    guard.copy("Fake-Passw0rd-1!")
    board.value = "something the user copied later"
    timers[0].fire()
    assert board.value == "something the user copied later" and board.clears == 0


def test_recopy_restarts_timer(setup: tuple[ClipboardGuard, FakeClipboard,
                                            list[FakeTimer]]) -> None:
    guard, board, timers = setup
    guard.copy("first")
    guard.copy("second")
    assert timers[0].cancelled and not timers[1].cancelled
    timers[0].fire()  # cancelled: nothing happens
    assert board.value == "second"
    timers[1].fire()
    assert board.value == ""


def test_clear_now_on_lock(setup: tuple[ClipboardGuard, FakeClipboard, list[FakeTimer]]
                           ) -> None:
    guard, board, timers = setup
    guard.copy("Fake-Passw0rd-1!")
    assert guard.clear_now() is True
    assert board.value == "" and timers[0].cancelled
    assert guard.clear_now() is False  # nothing of ours left


def test_clear_after_is_configurable(setup: tuple[ClipboardGuard, FakeClipboard,
                                                  list[FakeTimer]]) -> None:
    guard, _board, timers = setup
    guard.clear_after = 30
    guard.copy("x")
    assert timers[-1].seconds == 30
