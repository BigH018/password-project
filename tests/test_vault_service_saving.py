"""Vault service saving: .bak rotation, opening from .bak, damaged files, failed saves."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import MASTER
from vault_service_helpers import Factory, populate
from vaultkeeper.errors import (
    VaultAuthError,
    VaultIOError,
)
from vaultkeeper.storage import vault_file


def test_save_keeps_previous_version_and_backup_unlocks(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    populate(svc)  # vault: 1 account, .bak: empty vault
    svc.lock()
    restored = make_service()
    restored.unlock(MASTER, use_backup=True)
    assert restored.data.accounts == []


def test_damaged_vault_never_falls_back_to_backup(make_service: Factory,
                                                  vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    populate(svc)  # creates a valid .bak
    svc.lock()
    damaged = bytearray(vault_path.read_bytes())
    damaged[-1] ^= 0x01
    vault_path.write_bytes(bytes(damaged))
    bak_before = svc.backup_path.read_bytes()

    again = make_service()
    assert again.has_backup()
    with pytest.raises(VaultAuthError):
        again.unlock(MASTER)
    assert not again.is_unlocked
    assert vault_path.read_bytes() == bytes(damaged)  # nothing rewritten or swapped
    assert again.backup_path.read_bytes() == bak_before
    again.unlock(MASTER, use_backup=True)  # only an explicit request opens the .bak
    assert again.is_unlocked


def test_save_after_opening_backup_keeps_good_bak_and_damaged_copy(
    make_service: Factory, vault_path: Path
) -> None:
    """Regression: saving after opening .bak must NOT copy the damaged main file over .bak."""
    svc = make_service()
    svc.create(MASTER)
    populate(svc)  # .bak = good older version
    svc.lock()
    damaged = bytearray(vault_path.read_bytes())
    damaged[-1] ^= 0x01
    vault_path.write_bytes(bytes(damaged))
    good_bak = svc.backup_path.read_bytes()

    restored = make_service()
    restored.unlock(MASTER, use_backup=True)
    assert restored.opened_from_backup
    restored.save()

    assert restored.backup_path.read_bytes() == good_bak  # good backup untouched
    kept = restored.last_damaged_copy
    assert kept is not None and kept.name.startswith("test.vault.damaged-")
    assert kept.read_bytes() == bytes(damaged)  # damaged file preserved, not deleted
    assert not restored.opened_from_backup
    restored.lock()
    make_service().unlock(MASTER)  # main vault is healthy again


def test_save_never_rotates_a_damaged_main_file_into_bak(
    make_service: Factory, vault_path: Path
) -> None:
    """CR-L2: the main file got damaged on disk while unlocked: .bak keeps the good copy."""
    svc = make_service()
    svc.create(MASTER)
    populate(svc)
    good_previous = vault_path.read_bytes()
    svc.save()  # .bak = good_previous
    good_bak = svc.backup_path.read_bytes()
    assert good_bak == good_previous
    damaged = bytearray(vault_path.read_bytes())
    damaged[-1] ^= 0x01
    vault_path.write_bytes(bytes(damaged))

    svc.save()
    assert svc.backup_path.read_bytes() == good_bak  # NOT the damaged file
    kept = svc.last_damaged_copy
    assert kept is not None and kept.read_bytes() == bytes(damaged)
    svc.lock()
    make_service().unlock(MASTER)  # main vault is healthy again
    make_service().unlock(MASTER, use_backup=True)


def test_failed_save_after_opening_backup_keeps_vault_and_retries(
    make_service: Factory, vault_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-H1: the final replace fails while quarantining: nothing is lost, the next save retries."""
    svc = make_service()
    svc.create(MASTER)
    populate(svc)
    svc.lock()
    damaged = bytearray(vault_path.read_bytes())
    damaged[-1] ^= 0x01
    vault_path.write_bytes(bytes(damaged))
    good_bak = svc.backup_path.read_bytes()
    restored = make_service()
    restored.unlock(MASTER, use_backup=True)

    real = vault_file._replace

    def failing(src: Path, dst: Path) -> None:
        if dst == vault_path:
            raise OSError("disk went away")
        real(src, dst)

    with monkeypatch.context() as patch, pytest.raises(VaultIOError):
        patch.setattr(vault_file, "_replace", failing)
        restored.save()
    assert vault_path.read_bytes() == bytes(damaged)  # main file still there
    assert restored.backup_path.read_bytes() == good_bak
    assert restored.opened_from_backup and restored.last_damaged_copy is None
    assert not list(vault_path.parent.glob("*.damaged-*"))

    restored.save()  # retry quarantines properly
    assert restored.last_damaged_copy is not None
    assert restored.last_damaged_copy.read_bytes() == bytes(damaged)
    assert restored.backup_path.read_bytes() == good_bak

    # Later saves go back to the normal rotation (main -> .bak).
    again = make_service()
    again.unlock(MASTER)
    again.save()
    assert again.backup_path.read_bytes() != good_bak
    assert again.last_damaged_copy is None


def test_opened_from_backup_resets_on_lock(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    svc.save()
    svc.lock()
    svc.unlock(MASTER, use_backup=True)
    assert svc.opened_from_backup
    svc.lock()
    assert not svc.opened_from_backup


def test_has_backup_false_for_new_vault(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    assert not svc.has_backup()


def test_unlock_cleans_stale_temp_files(make_service: Factory, vault_path: Path) -> None:
    make_service().create(MASTER)
    vault_file.tmp_path(vault_path).write_bytes(b"stale")
    make_service().unlock(MASTER)
    assert not vault_file.tmp_path(vault_path).exists()


def test_dir_sync_failure_does_not_undo_a_save(make_service: Factory, vault_path: Path,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """CR-L9: the new file is in place, so the save must count (no rollback in memory)."""
    svc = make_service()
    svc.create(MASTER)

    def fail(_directory: Path) -> None:
        raise OSError("directory sync not supported here")

    monkeypatch.setattr(vault_file, "_fsync_dir", fail)
    populate(svc)  # saves; must not raise
    svc.lock()
    reopened = make_service()
    reopened.unlock(MASTER)
    assert len(reopened.data.accounts) == 1
