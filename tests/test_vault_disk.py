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


# --- SEC-M3: noticing a vault that went back in time ------------------------------------
OLDER, NEWER = "2026-09-01T10:00:00+00:00", "2026-10-01T10:00:00+00:00"


def test_went_back_in_time() -> None:
    from vaultkeeper.core.vault_disk import went_back_in_time

    assert went_back_in_time(NEWER, OLDER)
    assert not went_back_in_time(OLDER, NEWER)
    assert not went_back_in_time(NEWER, NEWER)
    assert not went_back_in_time(None, OLDER)  # never seen: nothing to compare
    assert not went_back_in_time("garbage", OLDER)


def test_remember_saved_at_keys_by_path_and_caps(tmp_path: Path) -> None:
    from vaultkeeper.config.constants import MAX_REMEMBERED_VAULTS
    from vaultkeeper.core.vault_disk import remember_saved_at, vault_key

    seen: dict[str, str] = {}
    path = tmp_path / "fake.vault"
    seen = remember_saved_at(seen, path, OLDER)
    assert seen == {vault_key(path): OLDER}
    assert remember_saved_at(seen, tmp_path / "." / "fake.vault", NEWER) == {
        vault_key(path): NEWER}  # same file, same key
    for n in range(MAX_REMEMBERED_VAULTS + 5):
        seen = remember_saved_at(seen, tmp_path / f"v{n}.vault", NEWER)
    assert len(seen) == MAX_REMEMBERED_VAULTS
    assert vault_key(tmp_path / f"v{MAX_REMEMBERED_VAULTS + 4}.vault") in seen  # newest kept
