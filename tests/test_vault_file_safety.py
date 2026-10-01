"""vault_file safety: exclusive temp files, shared-folder warning, directory sync failures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vault_file_helpers import (
    NEW,
    OLD,
    leftovers,
    ok,
    quarantine_setup,
)
from vaultkeeper.storage import vault_file as vf

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
    assert leftovers(existing) == []
    assert "(OSError)" in caplog.text and str(existing.parent) not in caplog.text


def test_dir_sync_failure_after_replace_keeps_quarantine_copy(
    existing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = quarantine_setup(existing)
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
