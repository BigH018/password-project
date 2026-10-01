"""BackupService: copies are byte-identical, rotation keeps N, interval and dirty rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FAST_KDF, MASTER, OTHER_MASTER
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


# --- CR-M1/SEC-M1: backups after a master-password change ----------------------------------


def test_after_password_change_backs_up_at_once(vault: VaultService, tmp_path: Path,
                                                clock: Clock) -> None:
    backups = _service(vault, tmp_path, clock, interval=60)
    backups.backup_now()
    vault.change_password(MASTER, OTHER_MASTER)
    target = backups.after_password_change()  # ignores the 60-minute interval
    assert target is not None
    VaultService(target, kdf_params=FAST_KDF).unlock(OTHER_MASTER)


def test_old_password_backups_found_by_salt(vault: VaultService, tmp_path: Path,
                                            clock: Clock) -> None:
    backups = _service(vault, tmp_path, clock)
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
    backups = _service(vault, tmp_path, clock)
    junk = tmp_path / "backups" / "my-backup-20200101-000000.vault"
    junk.parent.mkdir(parents=True)
    junk.write_bytes(b"not a vault")
    assert backups.backups_with_old_password() == []


def test_delete_backups_only_touches_this_vaults_backups(vault: VaultService, tmp_path: Path,
                                                         clock: Clock) -> None:
    backups = _service(vault, tmp_path, clock)
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
    backups = _service(vault, tmp_path, clock)
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


# --- CR-L1: rotation follows the timestamp and counter, not the file name -----------------


def test_same_second_backups_rotate_oldest_first(vault: VaultService, tmp_path: Path) -> None:
    backups = BackupService(vault.path, tmp_path / "bk", keep=3, min_interval_minutes=0,
                            stamp=lambda: "20260101-000001")
    made = [backups.backup_now() for _ in range(11)]  # base, -2, ..., -11 in one second
    assert made[0].name == "my-backup-20260101-000001.vault"
    assert made[10].name == "my-backup-20260101-000001-11.vault"
    assert backups.list_backups() == made[-3:]  # the newest three, oldest first


def test_rotation_orders_across_seconds_and_counters(vault: VaultService,
                                                     tmp_path: Path) -> None:
    stamps = iter(["20260101-000009", "20260101-000009", "20260101-000010"])
    backups = BackupService(vault.path, tmp_path / "bk", keep=10, min_interval_minutes=0,
                            stamp=lambda: next(stamps))
    made = [backups.backup_now() for _ in range(3)]
    assert backups.list_backups() == made


# --- CR-L3: full paths only, unreadable folders are friendly errors -------------------------


def test_backup_folder_must_be_a_full_path(vault: VaultService, clock: Clock) -> None:
    from vaultkeeper.errors import ValidationError

    backups = BackupService(vault.path, None, 10, 10, clock, clock.stamp)
    with pytest.raises(ValidationError) as info:
        backups.configure(Path("relative-backups"), 10, 10)
    assert info.value.field == "backup_dir" and "full path" in info.value.reason
    assert backups.backup_dir is None


def test_listing_an_unreadable_folder_is_a_friendly_error(
    vault: VaultService, tmp_path: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    backups = _service(vault, tmp_path, clock)
    backups.backup_now()

    def denied(_self: Path) -> None:
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "iterdir", denied)
    with pytest.raises(VaultIOError):
        backups.list_backups()

