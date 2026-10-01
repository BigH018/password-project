"""Backup and export dialogs: full paths, unreadable folders, no listing per keystroke (CR-L3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import FAST_KDF, MASTER, OTHER_MASTER
from vaultkeeper.core.backup import BackupService
from vaultkeeper.core.tasks import InlineTaskRunner
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import VaultIOError
from vaultkeeper.ui.backup_dialog import BackupDialog
from vaultkeeper.ui.export_dialog import ExportDialog


@pytest.fixture
def backups(tmp_path: Path) -> BackupService:
    svc = VaultService(tmp_path / "v.vault", kdf_params=FAST_KDF)
    svc.create(MASTER)
    return BackupService(svc.path, tmp_path / "bk", 10, 10)


@pytest.fixture
def dialog(qtbot: Any, backups: BackupService) -> BackupDialog:
    dlg = BackupDialog(backups, choose_folder=lambda _p, _c: "")
    qtbot.addWidget(dlg)
    return dlg


def test_typing_a_folder_does_not_list_it_on_every_keystroke(
        dialog: BackupDialog, backups: BackupService, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch) -> None:
    listed: list[int] = []
    real = backups.list_backups
    monkeypatch.setattr(backups, "list_backups", lambda: listed.append(1) or real())
    target = str(tmp_path / "typed-folder")
    for n in range(1, len(target) + 1):
        dialog.folder.setText(target[:n])  # one keystroke at a time
    assert listed == []
    assert dialog.refresh_timer.isActive()
    dialog.refresh_timer.timeout.emit()  # the user paused
    assert len(listed) == 1 and backups.backup_dir == tmp_path / "typed-folder"


def test_relative_folder_is_refused(dialog: BackupDialog, backups: BackupService) -> None:
    dialog.folder.setText("relative-backups")
    dialog.save_button.click()
    assert dialog.isVisible() or dialog.result() == 0
    assert "full" in dialog.error_label.text().lower()
    assert backups.backup_dir is not None and backups.backup_dir.is_absolute()


def test_unreadable_folder_is_reported_in_the_dialog(dialog: BackupDialog,
                                                     backups: BackupService,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    def denied() -> list[Path]:
        raise VaultIOError("Could not read the backup folder.")

    monkeypatch.setattr(backups, "list_backups", denied)
    dialog.folder.setText(str(backups.backup_dir))
    dialog.refresh_timer.timeout.emit()  # must not raise (no "Something went wrong")
    assert "can't read" in dialog.status.text().lower()


def test_export_needs_a_full_path(qtbot: Any, tmp_path: Path) -> None:
    written: list[Path] = []
    dialog = ExportDialog(b"{}", tmp_path / "v.vault", InlineTaskRunner(), lambda: None,
                          tmp_path / "export.vault",
                          writer=lambda _p, target, *_a, **_k: written.append(target) or True)
    qtbot.addWidget(dialog)
    dialog.path_edit.setText("relative-export")
    dialog.password.setText(OTHER_MASTER)
    dialog.confirm.setText(OTHER_MASTER)
    dialog.export_button.click()
    assert written == [] and "full path" in dialog.error_label.text()

