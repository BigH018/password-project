"""Generic error notice: wording, one at a time, opened from the event loop, any thread."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PyQt5.QtWidgets import QMessageBox

from vaultkeeper.ui import error_dialog as ed


def test_box_wording_and_log_button(qtbot: Any, tmp_path: Path) -> None:
    box = ed.build_error_box(tmp_path)
    qtbot.addWidget(box)
    assert box.windowTitle() == ed.ERROR_TITLE
    assert "accounts are safe" in box.text() and "restarting" in box.text()
    assert str(tmp_path) in box.informativeText()
    assert ed.OPEN_LOGS in [b.text() for b in box.buttons()]


def test_box_without_log_folder(qtbot: Any) -> None:
    box = ed.build_error_box(None)
    qtbot.addWidget(box)
    assert box.informativeText() == ""
    assert ed.OPEN_LOGS not in [b.text() for b in box.buttons()]


class _FakeBox:
    def __init__(self, clicked_text: str) -> None:
        self._text = clicked_text

    def deleteLater(self) -> None:  # noqa: N802 - Qt API (run_modal)
        pass

    def exec_(self) -> int:
        return 0

    def clickedButton(self) -> Any:  # noqa: N802 - Qt API
        text = self._text
        return type("B", (), {"text": lambda _self: text})()


def test_open_log_folder_only_when_asked(monkeypatch: Any, tmp_path: Path) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(ed, "build_error_box", lambda _folder: _FakeBox(ed.OPEN_LOGS))
    ed.show_error_box(tmp_path, opener=opened.append)
    assert opened == [tmp_path]
    monkeypatch.setattr(ed, "build_error_box", lambda _folder: _FakeBox("OK"))
    ed.show_error_box(tmp_path, opener=opened.append)
    assert opened == [tmp_path]


def test_reporter_shows_from_event_loop_once_at_a_time(qtbot: Any, tmp_path: Path) -> None:
    shown: list[Path | None] = []
    reporter: ed.ErrorReporter

    def show(folder: Path | None) -> None:
        shown.append(folder)
        reporter.report()  # another error while the box is open: dropped
        qtbot.wait(10)

    reporter = ed.ErrorReporter(tmp_path, show=show)
    reporter.report()
    assert shown == []  # queued: never opened inside the failing call
    qtbot.waitUntil(lambda: shown == [tmp_path], timeout=2000)
    qtbot.wait(50)
    assert reporter.shown == 1 and not reporter.showing


def test_reporter_from_worker_thread(qtbot: Any) -> None:
    on_thread: list[int] = []
    reporter = ed.ErrorReporter(None, show=lambda _f: on_thread.append(threading.get_ident()))
    worker = threading.Thread(target=reporter.report)
    worker.start()
    worker.join()
    qtbot.waitUntil(lambda: bool(on_thread), timeout=2000)
    assert on_thread == [threading.get_ident()]  # shown on the UI thread


def test_a_box_is_a_message_box(qtbot: Any) -> None:
    box = ed.build_error_box(None)
    qtbot.addWidget(box)
    assert isinstance(box, QMessageBox) and box.icon() == QMessageBox.Warning


# --- friendly validation wording --------------------------------------------------------------


def test_validation_text_uses_on_screen_labels() -> None:
    from vaultkeeper.errors import ValidationError
    from vaultkeeper.ui.messages import error_text

    assert error_text(ValidationError("tags", "a label must not contain commas")) == (
        "Labels: a label must not contain commas.")
    assert error_text(ValidationError("game_id", "is not an existing game")) == (
        "Game is not an existing game.")
    assert error_text(ValidationError("login_username", "is required")) == "Login is required."
    # Extra fields pass the user's own label: kept exactly as typed.
    assert error_text(ValidationError("Main Legend", "must be a number")) == (
        "Main Legend must be a number.")


def test_every_core_field_name_has_a_label() -> None:
    import re

    from vaultkeeper.ui.messages import FIELD_LABELS

    core = Path(__file__).resolve().parents[2] / "src" / "vaultkeeper" / "core"
    names: set[str] = set()
    for source in core.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        names |= set(re.findall(r'ValidationError\(\s*"([a-z_]+)"', text))
        names |= set(re.findall(r'clean_\w+\([^()]*?"([a-z_]+)"', text))
    assert names, "the scan found nothing: update the patterns"
    assert names <= set(FIELD_LABELS), sorted(names - set(FIELD_LABELS))
