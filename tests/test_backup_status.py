"""BackupService: failures, the password-change helpers and the prepare/run/finish split."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from backup_helpers import Clock, service
from conftest import FAST_KDF, MASTER, OTHER_MASTER
from vaultkeeper.core.backup import BackupService
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import VaultIOError

# --- CR-M1/SEC-M1: backups after a master-password change ----------------------------------


def test_after_password_change_backs_up_at_once(vault: VaultService, tmp_path: Path,
                                                clock: Clock) -> None:
    backups = service(vault, tmp_path, clock, interval=60)
    backups.backup_now()
    vault.change_password(MASTER, OTHER_MASTER)
    target = backups.after_password_change()  # ignores the 60-minute interval
    assert target is not None
    VaultService(target, kdf_params=FAST_KDF).unlock(OTHER_MASTER)


def test_old_password_backups_found_by_salt(vault: VaultService, tmp_path: Path,
                                            clock: Clock) -> None:
    backups = service(vault, tmp_path, clock)
    first = backups.backup_now()
    second = backups.backup_now()
    assert backups.backups_with_old_password() == []
    vault.change_password(MASTER, OTHER_MASTER)
    assert not backups.has_backup_with_current_password()
    assert backups.backups_with_old_password() == [first, second]
    newest = backups.after_password_change()
    assert backups.has_backup_with_current_password()
    assert backups.backups_with_old_password() == [first, second]
    assert backups.delete_backups([first, second]) == 2
    assert backups.list_backups() == [newest]


def test_unreadable_backup_is_never_offered_for_deletion(vault: VaultService, tmp_path: Path,
                                                         clock: Clock) -> None:
    backups = service(vault, tmp_path, clock)
    junk = tmp_path / "backups" / "my-backup-20200101-000000.vault"
    junk.parent.mkdir(parents=True)
    junk.write_bytes(b"not a vault")
    assert backups.backups_with_old_password() == []


def test_delete_backups_only_touches_this_vaults_backups(vault: VaultService, tmp_path: Path,
                                                         clock: Clock) -> None:
    backups = service(vault, tmp_path, clock)
    kept = backups.backup_now()
    other = tmp_path / "backups" / "notes.txt"
    other.write_text("fake", encoding="utf-8")
    assert backups.delete_backups([vault.path, other, tmp_path / "elsewhere.vault"]) == 0
    assert vault.path.exists() and other.exists() and kept.exists()


# --- CR-H2: backup failures are recorded (and logged without details) ----------------------


def test_failed_backup_is_recorded_and_logged_without_details(
    vault: VaultService, tmp_path: Path, clock: Clock, caplog: pytest.LogCaptureFixture
) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("fake", encoding="utf-8")
    backups = BackupService(vault.path, blocker / "bk", 10, 10, clock, clock.stamp)
    with caplog.at_level("WARNING"), pytest.raises(VaultIOError):
        backups.backup_now()
    assert backups.last_failure is not None and backups.last_success is None
    assert "Backup failed (" in caplog.text
    assert str(tmp_path) not in caplog.text and "not-a-folder" not in caplog.text


def test_success_clears_the_failure(vault: VaultService, tmp_path: Path, clock: Clock) -> None:
    backups = BackupService(vault.path, tmp_path / "bk", 10, 10, clock, clock.stamp,
                            last_failure="2026-01-01T00:00:00+00:00")
    assert backups.last_failure is not None
    backups.backup_now()
    assert backups.last_failure is None
    assert backups.last_success is not None and backups.last_success.endswith("+00:00")


def test_unreadable_folder_becomes_a_friendly_error(
    vault: VaultService, tmp_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    backups = service(vault, tmp_path, clock)
    backups.backup_now()

    def denied(_self: Path) -> None:
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "iterdir", denied)
    with pytest.raises(VaultIOError):
        backups.backup_now()
    assert backups.last_failure is not None


def test_lock_time_failure_is_recorded(vault: VaultService, tmp_path: Path,
                                       clock: Clock) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("fake", encoding="utf-8")
    backups = BackupService(vault.path, blocker / "bk", 10, 10, clock, clock.stamp)
    backups.dirty = True
    with pytest.raises(VaultIOError):
        backups.on_lock_or_exit()
    assert backups.last_failure is not None


# --- CR-L6: prepare (caller's thread) / run (worker) / finish (caller's thread) ------------


def test_prepare_run_finish_split(vault: VaultService, tmp_path: Path, clock: Clock,
                                  monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    from vaultkeeper.core.backup import run_backup_job

    backups = service(vault, tmp_path, clock)
    real_iterdir = Path.iterdir

    def no_listing_here(self: Path) -> Any:
        if threading.current_thread() is threading.main_thread():
            raise AssertionError("the backup folder must only be listed on the worker")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", no_listing_here)
    job = backups.prepare()
    assert job.data == vault.path.read_bytes() and "data" not in repr(job)
    result: list[Path] = []
    worker = threading.Thread(target=lambda: result.append(run_backup_job(job)))
    worker.start()
    worker.join(timeout=10)
    assert result and result[0].read_bytes() == job.data
    assert backups.last_success is None  # nothing recorded until finish (caller's thread)
    backups.finish(job, None)
    assert backups.last_success is not None and backups.last_failure is None


def test_failed_job_is_recorded_and_retried_after_the_next_save(
    vault: VaultService, tmp_path: Path, clock: Clock
) -> None:
    backups = service(vault, tmp_path, clock, interval=60)
    job = backups.prepare_after_save()
    assert job is not None and not backups.dirty
    error = backups.finish(job, OSError("usb stick pulled out"))
    assert isinstance(error, VaultIOError)
    assert backups.last_failure is not None and backups.dirty
    assert backups.prepare_after_save() is not None  # interval reset: retried at once


def test_lock_job_only_when_something_changed(vault: VaultService, tmp_path: Path,
                                              clock: Clock) -> None:
    backups = service(vault, tmp_path, clock)
    assert backups.prepare_on_lock_or_exit() is None
    backups.dirty = True
    assert backups.prepare_on_lock_or_exit() is not None
