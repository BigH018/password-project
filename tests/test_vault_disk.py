"""SEC-M2 backstop: never overwrite a vault file that changed on disk since it was loaded."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import MASTER, OTHER_MASTER
from fake_data import make_account, make_game
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.errors import VaultConflictError

Factory = Callable[..., VaultService]


def _with_account(service: VaultService) -> None:
    game = make_game()
    service.data.games.append(game)
    service.data.accounts.append(make_account(game))
    service.save()


def test_second_instance_cannot_overwrite_the_first(make_service: Factory,
                                                     vault_path: Path) -> None:
    first = make_service()
    first.create(MASTER)
    second = make_service()
    second.unlock(MASTER)
    _with_account(first)  # first instance saves
    saved_by_first = vault_path.read_bytes()

    second.data.games.append(make_game("Overwatch", "overwatch"))
    with pytest.raises(VaultConflictError) as info:
        second.save()
    assert str(vault_path) not in str(info.value) and vault_path.name not in str(info.value)
    assert vault_path.read_bytes() == saved_by_first  # nothing overwritten
    assert not list(vault_path.parent.glob("*.damaged-*"))

    second.lock()
    second.unlock(MASTER)  # lock + unlock loads the latest version
    assert len(second.data.accounts) == 1
    second.save()  # and saving works again


def test_restored_older_copy_is_not_silently_overwritten(make_service: Factory,
                                                         vault_path: Path) -> None:
    """E.g. a sync tool puts an older version of the file back while unlocked."""
    svc = make_service()
    svc.create(MASTER)
    older = vault_path.read_bytes()
    _with_account(svc)
    vault_path.write_bytes(older)
    with pytest.raises(VaultConflictError):
        svc.save()
    assert vault_path.read_bytes() == older


def test_own_saves_and_password_change_never_conflict(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    _with_account(svc)
    svc.save()
    svc.change_password(MASTER, OTHER_MASTER)
    svc.save()
    svc.lock()
    svc.unlock(OTHER_MASTER)
    svc.save()


def test_conflict_check_after_opening_backup_still_quarantines(make_service: Factory,
                                                                vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    _with_account(svc)
    svc.lock()
    damaged = bytearray(vault_path.read_bytes())
    damaged[-1] ^= 0x01
    vault_path.write_bytes(bytes(damaged))
    restored = make_service()
    restored.unlock(MASTER, use_backup=True)
    restored.save()  # no conflict: the damaged main file is copied aside
    assert restored.last_damaged_copy is not None
