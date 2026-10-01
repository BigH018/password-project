"""Welcome dialog, demo title, and controller details (demo create location)."""

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


def test_lock_closes_open_dialogs_and_clears_window(qtbot: Any, tmp_path: Path,
                                                    monkeypatch: Any) -> None:
    from vaultkeeper.config.settings import Settings
    from vaultkeeper.ui import app_controller
    from vaultkeeper.ui.qt_adapters import QtTaskRunner

    reopened: list[bool] = []
    monkeypatch.setattr(app_controller.AppController, "_unlock",
                        lambda self: reopened.append(True))
    controller = app_controller.AppController(
        Settings(), tmp_path / "settings.json", QtTaskRunner(), lambda p: None,  # type: ignore[arg-type, return-value]
    )
    qtbot.addWidget(controller.window)
    controller.service = None
    draft = QDialog(controller.window)
    draft.show()
    assert draft.isVisible()
    controller.lock()
    assert not draft.isVisible()
    assert controller.window.stack.currentWidget() is controller.window.locked_label


# --- SEC-M2: a vault open in another running copy is not opened again --------------------


def _start_controller(qtbot: Any, tmp_path: Path, monkeypatch: Any) -> tuple[Any, list[str]]:
    from conftest import FAST_KDF, MASTER
    from vaultkeeper.config.settings import Settings
    from vaultkeeper.core.vault_service import VaultService
    from vaultkeeper.ui import app_controller, messages
    from vaultkeeper.ui.qt_adapters import QtTaskRunner

    vault = tmp_path / "fake.vault"
    VaultService(vault, kdf_params=FAST_KDF).create(MASTER)
    events: list[str] = []

    class FakeUnlock:
        def __init__(self, service: VaultService, *_a: Any, **_k: Any) -> None:
            self.service, self.other_vault_path = service, None
            events.append("unlock prompt")

        def exec_(self) -> int:
            self.service.unlock(MASTER)
            return 1

    class FakeWelcome:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.choice, self.path = None, None
            events.append("welcome")

        def exec_(self) -> int:
            return 0

    monkeypatch.setattr(app_controller, "UnlockDialog", FakeUnlock)
    monkeypatch.setattr(app_controller, "WelcomeDialog", FakeWelcome)
    monkeypatch.setattr(messages, "show_error",
                        lambda _p, title, text: events.append(f"error: {text}"))
    controller = app_controller.AppController(
        Settings(vault_path=str(vault)), tmp_path / "settings.json", QtTaskRunner(),
        lambda p: VaultService(p, kdf_params=FAST_KDF))
    qtbot.addWidget(controller.window)
    return controller, events


def test_vault_open_elsewhere_is_refused_before_the_password(qtbot: Any, tmp_path: Path,
                                                             monkeypatch: Any) -> None:
    from vaultkeeper.ui.qt_adapters import VaultInstanceLock

    other_copy = VaultInstanceLock()
    assert other_copy.acquire(tmp_path / "fake.vault")
    controller, events = _start_controller(qtbot, tmp_path, monkeypatch)
    controller.start()
    assert "unlock prompt" not in events
    assert any(e.startswith("error: ") and "already open" in e for e in events)
    assert events[-1] == "welcome"
    assert controller.service is None
    other_copy.release()


def test_lock_file_held_while_open_and_released_on_quit(qtbot: Any, tmp_path: Path,
                                                        monkeypatch: Any) -> None:
    from vaultkeeper.ui.qt_adapters import VaultInstanceLock

    controller, events = _start_controller(qtbot, tmp_path, monkeypatch)
    controller.start()
    assert events == ["unlock prompt"] and controller.service.is_unlocked
    assert not VaultInstanceLock().acquire(tmp_path / "fake.vault")  # another copy can't
    controller.quit()
    probe = VaultInstanceLock()
    assert probe.acquire(tmp_path / "fake.vault")
    probe.release()
