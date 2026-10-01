"""Atomic save: verify-before-replace, .bak retention, failure injection at every step."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vaultkeeper.errors import VaultAuthError, VaultFormatError, VaultIOError
from vaultkeeper.storage import vault_file as vf

OLD = b"old-vault-bytes"
NEW = b"new-vault-bytes"


def ok(_data: bytes) -> None:
    """Verifier that accepts anything."""


class SimulatedCrash(BaseException):
    """Stands in for a process being killed mid-save."""


@pytest.fixture
def existing(tmp_path: Path) -> Path:
    path = tmp_path / "v.vault"
    vf.write_vault_atomic(path, OLD, ok)
    return path


def _leftovers(path: Path) -> list[Path]:
    return [p for p in (vf.tmp_path(path), path.with_name(path.name + ".bak.tmp")) if p.exists()]


def test_first_write_creates_file_without_backup(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "v.vault"
    vf.write_vault_atomic(path, NEW, ok)
    assert path.read_bytes() == NEW
    assert not vf.backup_path(path).exists()
    assert _leftovers(path) == []


def test_second_write_keeps_previous_as_bak(existing: Path) -> None:
    vf.write_vault_atomic(existing, NEW, ok)
    assert existing.read_bytes() == NEW
    assert vf.backup_path(existing).read_bytes() == OLD
    assert _leftovers(existing) == []


def test_verifier_receives_bytes_read_from_disk(existing: Path) -> None:
    seen: list[bytes] = []
    vf.write_vault_atomic(existing, NEW, seen.append)
    assert seen == [NEW]


def test_verify_failure_leaves_vault_untouched(existing: Path) -> None:
    def bad(_data: bytes) -> None:
        raise VaultAuthError()

    with pytest.raises(VaultIOError, match="verification"):
        vf.write_vault_atomic(existing, NEW, bad)
    assert existing.read_bytes() == OLD
    assert not vf.backup_path(existing).exists()
    assert _leftovers(existing) == []


def test_write_failure(existing: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_a: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(vf, "_write_and_sync", fail)
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok)
    assert existing.read_bytes() == OLD
    assert _leftovers(existing) == []


def test_backup_copy_failure(existing: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_a: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr(vf.shutil, "copyfileobj", fail)
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok)
    assert existing.read_bytes() == OLD
    assert _leftovers(existing) == []


def test_final_replace_failure(existing: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = vf._replace
    calls = {"n": 0}

    def replace(src: Path, dst: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 2:  # 1st = .bak staging, 2nd = tmp -> vault
            raise OSError("replace failed")
        real(src, dst)

    monkeypatch.setattr(vf, "_replace", replace)
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok)
    assert existing.read_bytes() == OLD
    assert _leftovers(existing) == []


@pytest.mark.parametrize("step", ["_write_and_sync", "_keep_previous_version", "_replace"])
def test_hard_crash_at_each_step_leaves_old_vault_readable(
    existing: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    """Simulate the process dying: no cleanup runs. The old vault must survive intact."""
    real = getattr(vf, step)

    def crash(*args: object) -> None:
        if step == "_write_and_sync":
            real(*args)  # tmp fully written, then die
        raise SimulatedCrash

    with monkeypatch.context() as patch, pytest.raises(SimulatedCrash):
        patch.setattr(vf, step, crash)
        patch.setattr(vf, "_remove_quietly", lambda _p: None)
        vf.write_vault_atomic(existing, NEW, ok)
    assert existing.read_bytes() == OLD

    vf.cleanup_stale_temp_files(existing)
    assert _leftovers(existing) == []
    assert existing.read_bytes() == OLD


def test_replace_retries_on_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = os.replace
    attempts = {"n": 0}

    def flaky(src: object, dst: object) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise PermissionError("locked by antivirus")
        real(src, dst)

    monkeypatch.setattr(vf.os, "replace", flaky)
    monkeypatch.setattr(vf, "REPLACE_RETRY_DELAY", 0)
    vf.write_vault_atomic(tmp_path / "v.vault", NEW, ok)
    assert attempts["n"] == 3


def test_quarantine_copies_current_aside_and_leaves_bak(existing: Path) -> None:
    vf.write_vault_atomic(existing, b"second", ok)  # .bak = OLD, vault = second
    target = vf.damaged_path(existing, "20260101-000000")
    vf.write_vault_atomic(existing, NEW, ok, quarantine_as=target)
    assert existing.read_bytes() == NEW
    assert vf.backup_path(existing).read_bytes() == OLD  # untouched
    assert target.read_bytes() == b"second"
    assert _leftovers(existing) == []


def test_quarantine_verify_failure_changes_nothing(existing: Path) -> None:
    target = vf.damaged_path(existing, "20260101-000000")

    def bad(_data: bytes) -> None:
        raise VaultAuthError()

    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, bad, quarantine_as=target)
    assert existing.read_bytes() == OLD and not target.exists()


def test_damaged_path_never_collides(existing: Path) -> None:
    first = vf.damaged_path(existing, "20260101-000000")
    first.write_bytes(b"x")
    second = vf.damaged_path(existing, "20260101-000000")
    assert second != first and second.name.endswith("-2")
    assert first.name == "v.vault.damaged-20260101-000000"


def test_cleanup_never_touches_vault_or_bak(existing: Path) -> None:
    vf.write_vault_atomic(existing, NEW, ok)
    vf.tmp_path(existing).write_bytes(b"stale")
    vf.cleanup_stale_temp_files(existing)
    assert existing.exists() and vf.backup_path(existing).exists()
    assert not vf.tmp_path(existing).exists()


def test_read_missing_and_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(VaultIOError):
        vf.read_vault_bytes(tmp_path / "missing.vault")
    big = tmp_path / "big.vault"
    big.write_bytes(b"x" * 100)
    monkeypatch.setattr(vf, "MAX_VAULT_BYTES", 50)
    with pytest.raises(VaultFormatError):
        vf.read_vault_bytes(big)


# --- CR-H1 / SEC-Low8: quarantine mode never leaves the vault missing ----------------------


def _quarantine_setup(existing: Path) -> Path:
    vf.write_vault_atomic(existing, b"second", ok)  # .bak = OLD (good), vault = "second"
    return vf.damaged_path(existing, "20260101-000000")


def _fail_final_replace(monkeypatch: pytest.MonkeyPatch, path: Path,
                        error: BaseException) -> None:
    real = vf._replace

    def replace(src: Path, dst: Path) -> None:
        if src == vf.tmp_path(path) and dst == path:
            raise error
        real(src, dst)

    monkeypatch.setattr(vf, "_replace", replace)


def test_quarantine_final_replace_failure_keeps_vault_and_bak(
    existing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _quarantine_setup(existing)
    _fail_final_replace(monkeypatch, existing, OSError("replace failed"))
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok, quarantine_as=target)
    assert existing.read_bytes() == b"second"  # main file still there, unchanged
    assert vf.backup_path(existing).read_bytes() == OLD
    assert not target.exists()  # the half-done quarantine is undone
    assert _leftovers(existing) == []


def test_quarantine_hard_crash_before_final_replace_keeps_main_file(
    existing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process dies after the damaged copy is made but before the new file is in place."""
    target = _quarantine_setup(existing)
    with monkeypatch.context() as patch, pytest.raises(SimulatedCrash):
        _fail_final_replace(patch, existing, SimulatedCrash())
        patch.setattr(vf, "_remove_quietly", lambda _p: None)
        vf.write_vault_atomic(existing, NEW, ok, quarantine_as=target)
    vf.cleanup_stale_temp_files(existing)  # what the next unlock does
    assert existing.read_bytes() == b"second"
    assert vf.backup_path(existing).read_bytes() == OLD


def test_quarantine_copy_never_overwrites_an_existing_file(existing: Path) -> None:
    target = _quarantine_setup(existing)
    target.write_bytes(b"earlier damaged copy")
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok, quarantine_as=target)
    assert target.read_bytes() == b"earlier damaged copy"
    assert existing.read_bytes() == b"second"


# --- SEC-Low7: temp files are created exclusively, never written through a link -----------


def _record_open_flags(monkeypatch: pytest.MonkeyPatch, module: object) -> list[int]:
    real = os.open
    flags_seen: list[int] = []

    def spy(path: object, flags: int, *args: object) -> int:
        flags_seen.append(flags)
        return real(path, flags, *args)

    monkeypatch.setattr(module.os, "open", spy)  # type: ignore[attr-defined]
    return flags_seen


def test_temp_files_are_opened_exclusively(existing: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    flags_seen = _record_open_flags(monkeypatch, vf)
    vf.tmp_path(existing).write_bytes(b"stale leftover")  # an earlier crash left one
    vf.write_vault_atomic(existing, NEW, ok)
    writes = [f for f in flags_seen if f & os.O_CREAT]
    assert writes and all(f & os.O_EXCL for f in writes)
    assert existing.read_bytes() == NEW and vf.backup_path(existing).read_bytes() == OLD


def test_backup_staging_file_is_created_exclusively(existing: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_open = builtins.open
    modes: list[str] = []

    def spy(file: object, mode: str = "r", *args: object, **kwargs: object) -> object:
        if str(file).endswith(".bak.tmp"):
            modes.append(mode)
        return real_open(file, mode, *args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(builtins, "open", spy)
    monkeypatch.setattr(vf.shutil, "copyfile", lambda *_a: pytest.fail("follows links"))
    vf.write_vault_atomic(existing, NEW, ok)
    assert modes and all("x" in m for m in modes if "w" in m or "x" in m)


def test_a_planted_link_is_never_written_through(existing: Path, tmp_path: Path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"precious")
    try:
        vf.tmp_path(existing).symlink_to(victim)
    except OSError:
        pytest.skip("creating symlinks needs extra rights on this system")
    vf.write_vault_atomic(existing, NEW, ok)
    assert victim.read_bytes() == b"precious"
    assert existing.read_bytes() == NEW



# --- SEC-Low7: warn when other users of the PC may be able to write to the vault's folder --


@pytest.mark.parametrize(
    ("vault", "shared"),
    [("C:/fake.vault", True),  # drive root
     ("C:/Vaults/fake.vault", True),  # one level below: inherits "any signed-in user: write"
     ("E:/fake.vault", True),  # USB stick root (often no permissions at all)
     ("C:/Users/Public/Documents/fake.vault", True),
     ("C:/Users/FakeUser/Documents/VaultKeeper/fake.vault", False),
     ("D:/Games/Accounts/fake.vault", False)],
)
def test_shared_folder_heuristic_on_windows(vault: str, shared: bool) -> None:
    assert vf.folder_may_be_shared(Path(vault), platform="win32",
                                   public=Path("C:/Users/Public")) is shared


@pytest.mark.parametrize(("mode", "shared"), [(0o40700, False), (0o40755, False),
                                              (0o40775, True), (0o40777, True)])
def test_shared_folder_heuristic_on_posix(tmp_path: Path, mode: int, shared: bool) -> None:
    assert vf.folder_may_be_shared(tmp_path / "fake.vault", platform="linux",
                                   mode_of=lambda _p: mode) is shared


# --- CR-L9: a failed directory sync after a successful replace is not a failed save --------


def _failing_dir_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_directory: Path) -> None:
        raise OSError("directory sync not supported here")

    monkeypatch.setattr(vf, "_fsync_dir", fail)


def test_dir_sync_failure_after_replace_still_counts_as_saved(
    existing: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _failing_dir_sync(monkeypatch)
    with caplog.at_level("WARNING"):
        vf.write_vault_atomic(existing, NEW, ok)  # no "could not save"
    assert existing.read_bytes() == NEW and vf.backup_path(existing).read_bytes() == OLD
    assert _leftovers(existing) == []
    assert "(OSError)" in caplog.text and str(existing.parent) not in caplog.text


def test_dir_sync_failure_after_replace_keeps_quarantine_copy(
    existing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = _quarantine_setup(existing)
    _failing_dir_sync(monkeypatch)
    vf.write_vault_atomic(existing, NEW, ok, quarantine_as=target)
    assert existing.read_bytes() == NEW and target.read_bytes() == b"second"


def test_dir_sync_failure_after_copy_still_counts_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _failing_dir_sync(monkeypatch)
    target = tmp_path / "backups" / "fake-backup.vault"
    vf.write_bytes_atomic(target, NEW, ok)
    assert target.read_bytes() == NEW
