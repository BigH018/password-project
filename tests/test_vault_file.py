"""Atomic save: verify-before-replace, .bak retention, failure injection at every step."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vault_file_helpers import (
    NEW,
    OLD,
    SimulatedCrash,
    leftovers,
    ok,
    quarantine_setup,
)
from vaultkeeper.errors import VaultAuthError, VaultFormatError, VaultIOError
from vaultkeeper.storage import vault_file as vf


def test_first_write_creates_file_without_backup(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "v.vault"
    vf.write_vault_atomic(path, NEW, ok)
    assert path.read_bytes() == NEW
    assert not vf.backup_path(path).exists()
    assert leftovers(path) == []


def test_second_write_keeps_previous_as_bak(existing: Path) -> None:
    vf.write_vault_atomic(existing, NEW, ok)
    assert existing.read_bytes() == NEW
    assert vf.backup_path(existing).read_bytes() == OLD
    assert leftovers(existing) == []


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
    assert leftovers(existing) == []


def test_write_failure(existing: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_a: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(vf, "_write_and_sync", fail)
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok)
    assert existing.read_bytes() == OLD
    assert leftovers(existing) == []


def test_backup_copy_failure(existing: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_a: object) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr(vf.shutil, "copyfileobj", fail)
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok)
    assert existing.read_bytes() == OLD
    assert leftovers(existing) == []


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
    assert leftovers(existing) == []


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
    assert leftovers(existing) == []
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
    assert leftovers(existing) == []


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
    target = quarantine_setup(existing)
    _fail_final_replace(monkeypatch, existing, OSError("replace failed"))
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok, quarantine_as=target)
    assert existing.read_bytes() == b"second"  # main file still there, unchanged
    assert vf.backup_path(existing).read_bytes() == OLD
    assert not target.exists()  # the half-done quarantine is undone
    assert leftovers(existing) == []


def test_quarantine_hard_crash_before_final_replace_keeps_main_file(
    existing: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process dies after the damaged copy is made but before the new file is in place."""
    target = quarantine_setup(existing)
    with monkeypatch.context() as patch, pytest.raises(SimulatedCrash):
        _fail_final_replace(patch, existing, SimulatedCrash())
        patch.setattr(vf, "_remove_quietly", lambda _p: None)
        vf.write_vault_atomic(existing, NEW, ok, quarantine_as=target)
    vf.cleanup_stale_temp_files(existing)  # what the next unlock does
    assert existing.read_bytes() == b"second"
    assert vf.backup_path(existing).read_bytes() == OLD


def test_quarantine_copy_never_overwrites_an_existing_file(existing: Path) -> None:
    target = quarantine_setup(existing)
    target.write_bytes(b"earlier damaged copy")
    with pytest.raises(VaultIOError):
        vf.write_vault_atomic(existing, NEW, ok, quarantine_as=target)
    assert target.read_bytes() == b"earlier damaged copy"
    assert existing.read_bytes() == b"second"





















