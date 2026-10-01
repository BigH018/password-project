"""BackupService: copies are byte-identical, rotation keeps N, interval and dirty rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FAST_KDF, MASTER
from vaultkeeper.core.backup import BackupService
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import VaultIOError


class Clock:
    def __init__(self) -> None:
        self.now = 10_000.0
        self.n = 0

    def __call__(self) -> float:
        return self.now

    def stamp(self) -> str:
        self.n += 1
        return f"20260101-0000{self.n:02d}"


@pytest.fixture
def vault(tmp_path: Path) -> VaultService:
    svc = VaultService(tmp_path / "main" / "my.vault", kdf_params=FAST_KDF)
    svc.create(MASTER)
    return svc


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _service(vault: VaultService, tmp_path: Path, clock: Clock, keep: int = 10,
             interval: int = 10) -> BackupService:
    return BackupService(vault.path, tmp_path / "backups", keep, interval, clock, clock.stamp)


def test_backup_now_is_identical_and_opens(vault: VaultService, tmp_path: Path,
                                           clock: Clock) -> None:
    backups = _service(vault, tmp_path, clock)
    target = backups.backup_now()
    assert target.name == "my-backup-20260101-000001.vault"
    assert target.read_bytes() == vault.path.read_bytes()
    VaultService(target, kdf_params=FAST_KDF).unlock(MASTER)  # same master password


def test_disabled_without_folder(vault: VaultService, clock: Clock) -> None:
    backups = BackupService(vault.path, None, 10, 10, clock, clock.stamp)
    assert not backups.enabled and backups.after_save() is None
    with pytest.raises(VaultIOError, match="backup folder"):
        backups.backup_now()


def test_rotation_keeps_newest(vault: VaultService, tmp_path: Path, clock: Clock) -> None:
    backups = _service(vault, tmp_path, clock, keep=3)
    made = [backups.backup_now() for _ in range(5)]
    assert backups.list_backups() == made[-3:]
    unrelated = tmp_path / "backups" / "notes.vault"
    unrelated.write_bytes(b"not ours")
    backups.backup_now()
    assert unrelated.exists()  # rotation only touches this vault's backups


def test_after_save_respects_interval(vault: VaultService, tmp_path: Path,
                                      clock: Clock) -> None:
    backups = _service(vault, tmp_path, clock, interval=10)
    assert backups.after_save() is not None  # first save: back up
    clock.now += 5 * 60
    assert backups.after_save() is None and backups.dirty  # too soon, but remembered
    clock.now += 5 * 60
    assert backups.after_save() is not None and not backups.dirty


def test_lock_or_exit_only_if_changed(vault: VaultService, tmp_path: Path,
                                      clock: Clock) -> None:
    backups = _service(vault, tmp_path, clock)
    assert backups.on_lock_or_exit() is None  # nothing changed
    backups.after_save()
    clock.now += 60
    backups.after_save()  # throttled -> dirty
    assert backups.on_lock_or_exit() is not None
    assert backups.on_lock_or_exit() is None


def test_wired_to_vault_saves(vault: VaultService, tmp_path: Path, clock: Clock) -> None:
    backups = _service(vault, tmp_path, clock)
    vault.on_saved.append(backups.after_save)
    vault.save()
    assert len(backups.list_backups()) == 1


def test_broken_listener_never_breaks_saving(vault: VaultService) -> None:
    def boom() -> None:
        raise VaultIOError("backup disk unplugged")

    vault.on_saved.append(boom)
    vault.save()  # must not raise


def test_same_folder_warning(vault: VaultService, clock: Clock) -> None:
    beside = BackupService(vault.path, vault.path.parent, 10, 10, clock, clock.stamp)
    assert beside.same_folder_as_vault()


def test_name_collision_gets_suffix(vault: VaultService, tmp_path: Path) -> None:
    backups = BackupService(vault.path, tmp_path / "backups", 10, 10,
                            stamp=lambda: "20260101-000000")
    first, second = backups.backup_now(), backups.backup_now()
    assert first != second and second.name.endswith("-2.vault")
