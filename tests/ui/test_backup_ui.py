"""Backups in the UI: what happens after a master-password change (CR-M1/SEC-M1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import FAST_KDF, MASTER, OTHER_MASTER
from vaultkeeper.config.settings import Settings
from vaultkeeper.core.backup import BackupService
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui import backup_dialog, messages


@pytest.fixture
def svc(tmp_path: Path) -> VaultService:
    service = VaultService(tmp_path / "v.vault", kdf_params=FAST_KDF)
    service.create(MASTER)
    return service


@pytest.fixture
def backups(svc: VaultService, tmp_path: Path) -> BackupService:
    return BackupService(svc.path, tmp_path / "bk", keep=10, min_interval_minutes=60)


def _asked(monkeypatch: pytest.MonkeyPatch, answer: bool) -> list[str]:
    asked: list[str] = []

    def fake_confirm(_parent: Any, _title: str, text: str, **_k: Any) -> bool:
        asked.append(text)
        return answer

    monkeypatch.setattr(messages, "confirm", fake_confirm)
    return asked


def test_offer_deletes_old_password_backups(qapp: Any, svc: VaultService,
                                            backups: BackupService,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    old = [backups.backup_now(), backups.backup_now()]
    svc.change_password(MASTER, OTHER_MASTER)
    asked = _asked(monkeypatch, True)
    note = backup_dialog.after_password_change(None, backups)
    assert asked and "OLD master password" in asked[0] and "2" in asked[0]
    assert "Deleted 2" in note
    remaining = backups.list_backups()
    assert len(remaining) == 1 and remaining[0] not in old
    VaultService(remaining[0], kdf_params=FAST_KDF).unlock(OTHER_MASTER)


def test_declining_keeps_old_backups_and_says_so(qapp: Any, svc: VaultService,
                                                 backups: BackupService,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    backups.backup_now()
    svc.change_password(MASTER, OTHER_MASTER)
    _asked(monkeypatch, False)
    note = backup_dialog.after_password_change(None, backups)
    assert "old master password" in note
    assert len(backups.list_backups()) == 2


def test_never_offers_deletion_without_a_new_backup(qapp: Any, svc: VaultService,
                                                    backups: BackupService,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    backups.backup_now()
    svc.change_password(MASTER, OTHER_MASTER)

    def failing_backup() -> Path:
        raise backup_dialog.VaultKeeperError("simulated")

    monkeypatch.setattr(backups, "backup_now", failing_backup)
    asked = _asked(monkeypatch, True)
    note = backup_dialog.after_password_change(None, backups)
    assert asked == [] and "old master password" in note
    assert len(backups.list_backups()) == 1


def test_no_backup_folder_means_nothing_to_do(qapp: Any, svc: VaultService,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    off = BackupService(svc.path, None, keep=10, min_interval_minutes=60)
    svc.change_password(MASTER, OTHER_MASTER)
    asked = _asked(monkeypatch, True)
    assert backup_dialog.after_password_change(None, off) == ""
    assert asked == []


def test_controller_backs_up_after_password_change(qtbot: Any, tmp_path: Path,
                                                   svc: VaultService,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    from vaultkeeper.ui import app_controller
    from vaultkeeper.ui.qt_adapters import QtTaskRunner

    settings = Settings(vault_path=str(svc.path), backup_dir=str(tmp_path / "bk"),
                        backup_min_interval_minutes=60)
    monkeypatch.setattr(app_controller.AppController, "_unlock", lambda self: None)
    controller = app_controller.AppController(settings, tmp_path / "s.json", QtTaskRunner(),
                                              lambda p: svc)
    qtbot.addWidget(controller.window)
    controller.service = svc
    controller._show_unlocked()
    svc.save()  # first save -> immediate backup (old password)
    assert controller.backups is not None and len(controller.backups.list_backups()) == 1

    class FakeChange:
        def __init__(self, service: VaultService, *_a: Any) -> None:
            self.service = service

        def exec_(self) -> int:
            self.service.change_password(MASTER, OTHER_MASTER)
            return 1

    monkeypatch.setattr(app_controller, "ChangePasswordDialog", FakeChange)
    _asked(monkeypatch, True)
    controller._change_password()
    remaining = controller.backups.list_backups()
    assert len(remaining) == 1  # old one deleted, new one made at once (despite interval)
    VaultService(remaining[0], kdf_params=FAST_KDF).unlock(OTHER_MASTER)
    assert "Deleted 1" in controller.window.statusBar().currentMessage()


# --- CR-H2: failures are visible until a backup works again --------------------------------


def _controller(qtbot: Any, tmp_path: Path, svc: VaultService, backup_dir: Path,
                monkeypatch: pytest.MonkeyPatch) -> Any:
    from vaultkeeper.ui import app_controller
    from vaultkeeper.ui.qt_adapters import QtTaskRunner

    settings = Settings(vault_path=str(svc.path), backup_dir=str(backup_dir),
                        backup_min_interval_minutes=60)
    monkeypatch.setattr(app_controller.AppController, "_unlock", lambda self: None)
    controller = app_controller.AppController(settings, tmp_path / "s.json", QtTaskRunner(),
                                              lambda p: svc)
    qtbot.addWidget(controller.window)
    controller.service = svc
    controller._show_unlocked()
    return controller


def _blocked_folder(tmp_path: Path) -> Path:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("fake", encoding="utf-8")
    return blocker / "bk"


def test_failed_backup_shows_a_banner_until_one_succeeds(
        qtbot: Any, tmp_path: Path, svc: VaultService,
        monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _controller(qtbot, tmp_path, svc, _blocked_folder(tmp_path), monkeypatch)
    window = controller.window
    assert window.backup_failed.isHidden()
    svc.save()  # after_save backup fails
    assert not window.backup_failed.isHidden()
    assert window.backup_failed.text().startswith("Last backup failed at ")
    assert "Check the backup folder" in window.backup_failed.text()
    assert controller.settings.current.backup_last_failure is not None

    controller.backups.configure(tmp_path / "good", 10, 60)
    controller._backup_now()
    assert window.backup_failed.isHidden()
    assert controller.settings.current.backup_last_failure is None
    assert controller.settings.current.backup_last_success is not None


def test_lock_time_failure_is_shown_after_the_next_unlock(
        qtbot: Any, tmp_path: Path, svc: VaultService,
        monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _controller(qtbot, tmp_path, svc, tmp_path / "good", monkeypatch)
    svc.save()  # first backup works
    svc.save()  # dirty, within the interval
    assert controller.window.backup_failed.isHidden()
    controller.backups.configure(_blocked_folder(tmp_path), 10, 60)
    controller.lock()  # the lock-time backup fails while the window is hidden
    assert controller.settings.current.backup_last_failure is not None

    svc.unlock(MASTER)
    controller._show_unlocked()
    assert not controller.window.backup_failed.isHidden()


def test_backups_dialog_shows_last_successful_backup(qtbot: Any, svc: VaultService,
                                                     backups: BackupService) -> None:
    dialog = backup_dialog.BackupDialog(backups, choose_folder=lambda _p, _c: "")
    qtbot.addWidget(dialog)
    assert "No successful backup yet" in dialog.last_backup.text()
    dialog.backup_now_button.click()
    assert dialog.last_backup.text().startswith("Last successful backup: ")
