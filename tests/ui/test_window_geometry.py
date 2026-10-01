"""Main window size/position: saved on lock and quit, restored at the next start."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from test_clipboard import FakeClipboard
from vaultkeeper.config.settings import Settings, load_settings
from vaultkeeper.ui import app_controller
from vaultkeeper.ui.main_window import MainWindow
from vaultkeeper.ui.qt_adapters import QtTaskRunner
from vaultkeeper.ui.session_guard import SessionGuard


def _shown_window(qtbot: Any, x: int = 40, y: int = 30, w: int = 1250, h: int = 420) -> MainWindow:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    window.setGeometry(x, y, w, h)
    return window


def test_geometry_text_round_trip(qtbot: Any) -> None:
    first = _shown_window(qtbot)
    text = first.geometry_text()
    assert text.isascii() and len(text) < 200
    other = MainWindow()
    qtbot.addWidget(other)
    assert other.size() != first.size()
    assert other.restore_geometry_text(text) is True
    other.show()
    assert other.size() == first.size() and first.height() == 420


def test_missing_or_garbage_geometry_is_ignored(qtbot: Any) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    default = window.size()
    assert window.restore_geometry_text(None) is False
    assert window.restore_geometry_text("") is False
    assert window.restore_geometry_text("AAAA") is False
    assert window.size() == default


def _controller(qtbot: Any, file: Path, settings: Settings) -> app_controller.AppController:
    ctrl = app_controller.AppController(
        settings, file, QtTaskRunner(), lambda p: None,  # type: ignore[arg-type, return-value]
        guard=SessionGuard(settings, backend=FakeClipboard()),
    )
    qtbot.addWidget(ctrl.window)
    return ctrl


def test_lock_and_quit_save_geometry(qtbot: Any, tmp_path: Path) -> None:
    file = tmp_path / "settings.json"
    ctrl = _controller(qtbot, file, Settings())
    ctrl.window.show()
    ctrl.window.setGeometry(50, 40, 1250, 400)
    ctrl.lock()
    saved = load_settings(file).window_geometry
    assert saved is not None and not ctrl.window.isVisible()

    ctrl.window.show()
    ctrl.window.setGeometry(60, 50, 1270, 350)
    ctrl.quit()
    assert load_settings(file).window_geometry not in (None, saved)


def test_hidden_window_does_not_overwrite_saved_geometry(qtbot: Any, tmp_path: Path) -> None:
    file = tmp_path / "settings.json"
    ctrl = _controller(qtbot, file, Settings())
    ctrl.quit()  # quit from the unlock prompt: window never shown
    assert not file.exists()


def test_start_restores_saved_geometry(qtbot: Any, tmp_path: Path) -> None:
    first = _shown_window(qtbot, w=1260, h=390)
    ctrl = _controller(qtbot, tmp_path / "settings.json",
                       Settings(window_geometry=first.geometry_text()))
    ctrl.window.show()
    assert ctrl.window.size() == first.size() and first.height() == 390
