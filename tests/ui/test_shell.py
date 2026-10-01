"""Welcome dialog and the 4a main-window shell (banner, lock action, demo title)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt5.QtWidgets import QDialog

from vaultkeeper.ui.main_window import MainWindow
from vaultkeeper.ui.welcome_dialog import WelcomeDialog


def test_welcome_create(qtbot: Any) -> None:
    dialog = WelcomeDialog(choose_file=lambda _p: "")
    qtbot.addWidget(dialog)
    dialog.create_button.click()
    assert dialog.choice == "create" and dialog.result() == QDialog.Accepted


def test_welcome_open_and_cancelled_open(qtbot: Any, tmp_path: Path) -> None:
    cancelled = WelcomeDialog(choose_file=lambda _p: "")
    qtbot.addWidget(cancelled)
    cancelled.open_button.click()
    assert cancelled.choice is None  # file picker cancelled: stay on the welcome screen

    chosen = WelcomeDialog(choose_file=lambda _p: str(tmp_path / "a.vault"))
    qtbot.addWidget(chosen)
    chosen.open_button.click()
    assert chosen.choice == "open" and chosen.path == tmp_path / "a.vault"


def test_main_window_locked_and_unlocked_states(qtbot: Any) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()
    assert window.banner.isHidden() and not window.lock_action.isEnabled()

    window.show_unlocked("C:/fake/path.vault", opened_from_backup=False)
    assert window.banner.isHidden() and window.lock_action.isEnabled()

    window.show_unlocked("C:/fake/path.vault", opened_from_backup=True)
    assert window.banner.isVisible()
    assert "backup copy itself is not touched" in window.banner.text()

    window.show_locked()
    assert window.banner.isHidden() and window.placeholder.text() == "Locked"


def test_lock_action_emits_signal(qtbot: Any) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show_unlocked("C:/fake/path.vault", opened_from_backup=False)
    with qtbot.waitSignal(window.lock_requested, timeout=1000):
        window.lock_action.trigger()


def test_demo_title(qtbot: Any) -> None:
    window = MainWindow(demo=True)
    qtbot.addWidget(window)
    assert "DEMO" in window.windowTitle()


def test_demo_controller_suggests_new_vaults_inside_demo_folder(
    qtbot: Any, tmp_path: Path, monkeypatch: Any
) -> None:
    from vaultkeeper.config.settings import Settings
    from vaultkeeper.ui import app_controller
    from vaultkeeper.ui.qt_adapters import QtTaskRunner

    captured: list[Path] = []

    class FakeCreate:
        def __init__(self, _factory: Any, _cancel: Any, suggested: Path, parent: Any) -> None:
            captured.append(suggested)
            self.service = None

        def exec_(self) -> int:
            return 0

    monkeypatch.setattr(app_controller, "CreateVaultDialog", FakeCreate)
    monkeypatch.setattr(app_controller.AppController, "_welcome", lambda self: None)
    controller = app_controller.AppController(
        Settings(), tmp_path / "settings.json", QtTaskRunner(), lambda p: None,  # type: ignore[arg-type, return-value]
        demo=True, new_vault_dir=tmp_path,
    )
    qtbot.addWidget(controller.window)
    controller._create()
    assert captured == [tmp_path / "new.vault"]
