"""QtTaskRunner: work off the UI thread, callbacks on it, cancelled results discarded."""

from __future__ import annotations

import threading
from typing import Any

from vaultkeeper.ui.qt_adapters import QtTaskRunner


def test_task_off_ui_thread_callback_on_ui_thread(qtbot: Any, qt_runner: QtTaskRunner) -> None:
    ui_thread = threading.get_ident()
    seen: dict[str, int] = {}
    qt_runner.submit(
        threading.get_ident,
        lambda worker: seen.update(worker=worker, callback=threading.get_ident()),
        lambda exc: None,
    )
    assert qt_runner.busy
    qtbot.waitUntil(lambda: "callback" in seen, timeout=5000)
    assert seen["worker"] != ui_thread
    assert seen["callback"] == ui_thread
    assert not qt_runner.busy


def test_errors_are_delivered(qtbot: Any, qt_runner: QtTaskRunner) -> None:
    errors: list[BaseException] = []

    def boom() -> None:
        raise ValueError("fake failure")

    qt_runner.submit(boom, lambda _r: None, errors.append)
    qtbot.waitUntil(lambda: bool(errors), timeout=5000)
    assert isinstance(errors[0], ValueError)


def test_cancelled_results_are_discarded(qtbot: Any, qt_runner: QtTaskRunner) -> None:
    release = threading.Event()
    calls: list[str] = []
    qt_runner.submit(lambda: release.wait(5), lambda _r: calls.append("ok"),
                     lambda _e: calls.append("err"))
    qt_runner.cancel_pending()
    assert not qt_runner.busy
    release.set()
    qtbot.wait(300)
    assert calls == []


def test_worker_threads_are_daemons(qtbot: Any, qt_runner: QtTaskRunner) -> None:
    """Daemon threads can't keep the process alive, so a hung task never blocks quitting."""
    release = threading.Event()
    seen: list[bool] = []
    qt_runner.submit(lambda: (seen.append(threading.current_thread().daemon), release.wait(5)),
                     lambda _r: None, lambda _e: None)
    qtbot.waitUntil(lambda: bool(seen), timeout=5000)
    assert seen == [True]
    qt_runner.cancel_pending()
    release.set()
