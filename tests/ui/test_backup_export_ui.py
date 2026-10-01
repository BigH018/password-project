"""Backups dialog, encrypted export dialog, and the controller's lock path (backup + clipboard)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtWidgets import QDialog

from conftest import FAST_KDF, MASTER, OTHER_MASTER
from test_clipboard import FakeClipboard, FakeTimer
from vaultkeeper import demo
from vaultkeeper.config.settings import Settings
from vaultkeeper.core.backup import BackupService
from vaultkeeper.core.exporter import write_export
from vaultkeeper.core.serialization import dumps_payload
from vaultkeeper.core.tasks import InlineTaskRunner
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.crypto import envelope
from vaultkeeper.ui.backup_dialog import BackupDialog
from vaultkeeper.ui.export_dialog import ExportDialog
from vaultkeeper.ui.session_guard import SessionGuard

# --- backups ----------------------------------------------------------------------------------


def _scheduler(timers: list[FakeTimer]) -> Callable[[float, Callable[[], None]], FakeTimer]:
    def schedule(seconds: float, fn: Callable[[], None]) -> FakeTimer:
        timers.append(FakeTimer(seconds, fn))
        return timers[-1]
    return schedule


@pytest.fixture
def unlocked(tmp_path: Path) -> VaultService:
    env = demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock(demo.DEMO_PASSWORD)
    return svc


@pytest.fixture
def board() -> FakeClipboard:
    return FakeClipboard()


def test_backup_dialog(qtbot: Any, unlocked: VaultService, tmp_path: Path) -> None:
    backups = BackupService(unlocked.path, None, 10, 10)
    dialog = BackupDialog(backups, choose_folder=lambda _p, _c: str(tmp_path / "usb"))
    qtbot.addWidget(dialog)
    assert "Backups are OFF" in dialog.warning.text()
    assert not dialog.backup_now_button.isEnabled()
    dialog.browse_button.click()
    assert backups.backup_dir == tmp_path / "usb" and dialog.warning.isHidden()
    dialog.backup_now_button.click()
    assert len(backups.list_backups()) == 1 and "1 backup(s)" in dialog.status.text()
    dialog.folder.setText(str(unlocked.path.parent))
    dialog.refresh_timer.timeout.emit()  # the user paused typing
    assert "same folder as your vault" in dialog.warning.text()
    dialog.reject()  # cancel restores the original (off)
    assert backups.backup_dir is None


# --- export -----------------------------------------------------------------------------------


def _writer(payload: bytes, target: Path, password: str, cancelled: Any = None) -> bool:
    return write_export(payload, target, password, kdf_params=FAST_KDF,
                        cancelled=cancelled or (lambda: False))


def test_export_dialog(qtbot: Any, unlocked: VaultService, tmp_path: Path) -> None:
    target = tmp_path / "my-export"
    dialog = ExportDialog(dumps_payload(unlocked.data), unlocked.path, InlineTaskRunner(),
                          lambda: None, target, writer=_writer)
    qtbot.addWidget(dialog)
    dialog.password.setText(OTHER_MASTER)
    dialog.confirm.setText("mismatch entirely here")
    dialog.export_button.click()
    assert "don't match" in dialog.error_label.text()
    dialog.confirm.setText(OTHER_MASTER)
    dialog.export_button.click()
    assert dialog.result() == QDialog.Accepted
    written = tmp_path / "my-export.vault"
    assert dialog.written_path == written and written.exists()
    envelope.open_with_password(written.read_bytes(), OTHER_MASTER)
    assert dialog.password.text() == ""


def test_export_refuses_existing_unless_ticked(qtbot: Any, unlocked: VaultService,
                                               tmp_path: Path) -> None:
    target = tmp_path / "old.vault"
    target.write_bytes(b"older export")
    dialog = ExportDialog(dumps_payload(unlocked.data), unlocked.path, InlineTaskRunner(),
                          lambda: None, target, writer=_writer)
    qtbot.addWidget(dialog)
    dialog.password.setText(OTHER_MASTER)
    dialog.confirm.setText(OTHER_MASTER)
    dialog.export_button.click()
    assert "already exists" in dialog.error_label.text()
    dialog.overwrite.setChecked(True)
    dialog.export_button.click()
    assert target.read_bytes() != b"older export"


def test_export_cancel_while_busy_writes_nothing(qtbot: Any, unlocked: VaultService,
                                                 tmp_path: Path, qt_runner: Any,
                                                 gate: Any) -> None:
    target = tmp_path / "cancelled.vault"

    def slow_writer(payload: bytes, path: Path, password: str, cancelled: Any) -> bool:
        return write_export(payload, path, password, kdf_params=FAST_KDF, kdf=gate.kdf,
                            cancelled=cancelled)

    dialog = ExportDialog(dumps_payload(unlocked.data), unlocked.path, qt_runner,
                          qt_runner.cancel_pending, target, writer=slow_writer)
    qtbot.addWidget(dialog)
    dialog.password.setText(OTHER_MASTER)
    dialog.confirm.setText(OTHER_MASTER)
    dialog.export_button.click()
    assert dialog.busy and gate.entered.wait(5)
    dialog.close()
    gate.release()
    qtbot.wait(400)
    assert not target.exists()


# --- controller lock path ---------------------------------------------------------------------


def test_lock_backs_up_changes_and_clears_clipboard(qtbot: Any, tmp_path: Path,
                                                    board: FakeClipboard,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from vaultkeeper.ui import app_controller
    from vaultkeeper.ui.qt_adapters import QtTaskRunner

    vault = tmp_path / "v.vault"
    svc = VaultService(vault, kdf_params=FAST_KDF)
    svc.create(MASTER)
    settings = Settings(vault_path=str(vault), backup_dir=str(tmp_path / "bk"),
                        backup_min_interval_minutes=60)
    guard = SessionGuard(settings, backend=board, schedule=_scheduler([]))
    monkeypatch.setattr(app_controller.AppController, "_unlock", lambda self: None)
    controller = app_controller.AppController(settings, tmp_path / "s.json", QtTaskRunner(),
                                              lambda p: svc, guard=guard,
                                              backup_runner=InlineTaskRunner())
    qtbot.addWidget(controller.window)
    controller.service = svc
    controller._show_unlocked()
    assert guard.armed
    svc.save()  # first save after unlock -> immediate backup
    svc.save()  # within the interval -> remembered as dirty
    assert controller.backups is not None and len(controller.backups.list_backups()) == 1
    guard.clipboard.copy("Fake-Passw0rd-1!")
    controller.lock()
    assert len(controller.backups.list_backups()) == 2  # dirty -> backed up on lock
    assert board.value == "" and not guard.armed and not svc.is_unlocked
