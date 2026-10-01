"""CR-L6: backups run off the UI thread, so a slow USB or network folder can't freeze the app."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from conftest import FAST_KDF, MASTER
from vaultkeeper.config.settings import Settings
from vaultkeeper.core import backup as backup_module
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui import app_controller
from vaultkeeper.ui.qt_adapters import QtTaskRunner


class SlowFolder:
    """Makes every backup write wait until released (a slow USB stick or network share)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.release = threading.Event()
        self.entered = threading.Event()
        real = backup_module.write_bytes_atomic

        def slow_write(*args: Any, **kwargs: Any) -> None:
            self.entered.set()
            self.release.wait(timeout=10)
            real(*args, **kwargs)

        monkeypatch.setattr(backup_module, "write_bytes_atomic", slow_write)


@pytest.fixture
def slow(monkeypatch: pytest.MonkeyPatch) -> Any:
    folder = SlowFolder(monkeypatch)
    yield folder
    folder.release.set()  # never leave a worker blocked


@pytest.fixture
def setup(qtbot: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    svc = VaultService(tmp_path / "v.vault", kdf_params=FAST_KDF)
    svc.create(MASTER)
    settings = Settings(vault_path=str(svc.path), backup_dir=str(tmp_path / "bk"),
                        backup_min_interval_minutes=60)
    monkeypatch.setattr(app_controller.AppController, "_unlock", lambda self: None)
    controller = app_controller.AppController(settings, tmp_path / "s.json", QtTaskRunner(),
                                              lambda p: svc, backup_runner=QtTaskRunner())
    qtbot.addWidget(controller.window)
    controller.service = svc
    controller._show_unlocked()
    return controller, svc


def test_saving_never_waits_for_a_slow_backup(qtbot: Any, setup: Any, slow: SlowFolder) -> None:
    controller, svc = setup
    svc.save()  # returns at once: the backup is still writing
    assert slow.entered.wait(timeout=5)
    assert controller.backups.list_backups() == []
    slow.release.set()
    qtbot.waitUntil(lambda: len(controller.backups.list_backups()) == 1, timeout=5000)
    qtbot.waitUntil(lambda: controller.window.statusBar().currentMessage() == "Backup saved.",
                    timeout=5000)
    assert controller.backups.last_success is not None


def test_lock_lets_a_running_backup_finish_and_records_it(qtbot: Any, setup: Any,
                                                          slow: SlowFolder) -> None:
    controller, svc = setup
    svc.save()
    assert slow.entered.wait(timeout=5)
    controller.lock()  # doesn't wait for the slow folder
    assert not svc.is_unlocked
    slow.release.set()
    qtbot.waitUntil(lambda: controller.backups.last_success is not None, timeout=5000)
    assert len(controller.backups.list_backups()) == 1
    assert controller.settings.current.backup_last_success is not None


def test_a_request_while_busy_runs_afterwards(qtbot: Any, setup: Any,
                                              slow: SlowFolder) -> None:
    controller, svc = setup
    svc.save()
    assert slow.entered.wait(timeout=5)
    controller._backup_now()  # while the first one is still writing
    slow.release.set()
    qtbot.waitUntil(lambda: len(controller.backups.list_backups()) == 2, timeout=5000)


def test_quit_waits_for_a_running_backup_then_makes_the_exit_backup(
        qtbot: Any, setup: Any, slow: SlowFolder) -> None:
    controller, svc = setup
    svc.save()
    assert slow.entered.wait(timeout=5)
    svc.save()  # a later change: the exit backup must include it
    timer = threading.Timer(0.3, slow.release.set)  # the slow folder finishes meanwhile
    timer.start()
    controller.quit()
    timer.join()
    assert len(controller.backups.list_backups()) == 2
