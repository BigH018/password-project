"""Vault lifecycle: create, unlock, wrong password, tamper, save, lock, change password, async."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from conftest import FAST_KDF, MASTER, OTHER_MASTER
from fake_data import make_account, make_game
from vaultkeeper.core.tasks import InlineTaskRunner
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.crypto.kdf import KdfParams
from vaultkeeper.errors import (
    VaultAuthError,
    VaultFormatError,
    VaultIOError,
    VaultLockedError,
    WeakPasswordError,
)
from vaultkeeper.storage import vault_file

Factory = Callable[..., VaultService]


def _populate(service: VaultService) -> None:
    game = make_game()
    service.data.games.append(game)
    service.data.accounts.append(make_account(game))
    service.save()


def test_create_then_unlock_round_trip(make_service: Factory, vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    assert svc.is_unlocked and vault_path.exists()
    _populate(svc)
    saved = (list(svc.data.games), list(svc.data.accounts))
    svc.lock()

    again = make_service()
    again.unlock(MASTER)
    assert (again.data.games, again.data.accounts) == saved


def test_file_contains_no_plaintext(make_service: Factory, vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)
    raw = vault_path.read_bytes()
    needles = (b"Fake-Passw0rd-1!", b"example.test", b"FakePlayer", b"Valorant", MASTER.encode())
    for needle in needles:
        assert needle not in raw


def test_create_enforces_policy_and_refuses_overwrite(make_service: Factory) -> None:
    with pytest.raises(WeakPasswordError):
        make_service().create("short")
    make_service().create(MASTER)
    with pytest.raises(VaultIOError):
        make_service().create(OTHER_MASTER)


def test_wrong_password_generic_error_with_delay(make_service: Factory) -> None:
    make_service().create(MASTER)
    delays: list[float] = []
    svc = make_service(wrong_password_delay=0.75, sleep=delays.append)
    with pytest.raises(VaultAuthError) as info:
        svc.unlock("wrong fake passphrase")
    assert str(info.value) == "Wrong password or the vault file is damaged."
    assert delays == [0.75]
    assert not svc.is_unlocked


@pytest.mark.parametrize("offset", [0, 9, 12, 25, 45, 53, 60, -1])
def test_tampered_file_fails(make_service: Factory, vault_path: Path, offset: int) -> None:
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)
    svc.lock()
    raw = bytearray(vault_path.read_bytes())
    raw[offset] ^= 0x01
    vault_path.write_bytes(bytes(raw))
    with pytest.raises((VaultAuthError, VaultFormatError)):
        make_service().unlock(MASTER)


def test_truncated_file_fails(make_service: Factory, vault_path: Path) -> None:
    make_service().create(MASTER)
    vault_path.write_bytes(vault_path.read_bytes()[:-5])
    with pytest.raises(VaultFormatError):
        make_service().unlock(MASTER)


def test_kdf_not_run_for_out_of_bounds_header(make_service: Factory, vault_path: Path) -> None:
    make_service().create(MASTER)
    raw = bytearray(vault_path.read_bytes())
    raw[12:16] = (50).to_bytes(4, "big")  # time_cost 50 > 10
    vault_path.write_bytes(bytes(raw))
    calls: list[Any] = []
    svc = make_service(kdf=lambda *a: calls.append(a) or bytearray(32))
    with pytest.raises(VaultFormatError):
        svc.unlock(MASTER)
    assert calls == []


def test_each_save_uses_fresh_nonce_same_salt(make_service: Factory, vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    headers = []
    for _ in range(5):
        svc.save()
        headers.append(vault_path.read_bytes()[:56])
    assert len({h[40:52] for h in headers}) == 5
    assert len({h[22:38] for h in headers}) == 1


def test_save_keeps_previous_version_and_backup_unlocks(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)  # vault: 1 account, .bak: empty vault
    svc.lock()
    restored = make_service()
    restored.unlock(MASTER, use_backup=True)
    assert restored.data.accounts == []


def test_damaged_vault_never_falls_back_to_backup(make_service: Factory,
                                                  vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)  # creates a valid .bak
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
    _populate(svc)  # .bak = good older version
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
    _populate(svc)
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


def test_password_change_rotates_old_file_normally(make_service: Factory,
                                                    vault_path: Path) -> None:
    """The file on disk is still under the OLD password: that's not damage."""
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)
    svc.change_password(MASTER, OTHER_MASTER)
    assert svc.last_damaged_copy is None
    assert not list(vault_path.parent.glob("*.damaged-*"))


def test_password_change_resaves_bak_under_new_password(make_service: Factory,
                                                         vault_path: Path) -> None:
    """CR-M1/SEC-M1: after a change, .bak must not still open with the old password."""
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)
    svc.change_password(MASTER, OTHER_MASTER)
    svc.lock()
    make_service().unlock(OTHER_MASTER, use_backup=True)
    with pytest.raises(VaultAuthError):
        make_service().unlock(MASTER, use_backup=True)


def test_password_change_succeeds_even_if_bak_refresh_fails(
    make_service: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)

    def fail(*_a: object) -> None:
        raise VaultIOError("simulated")

    with monkeypatch.context() as patch:
        patch.setattr(vault_file, "copy_file_verified", fail)
        svc.change_password(MASTER, OTHER_MASTER)
    svc.save()  # the next normal save rotates .bak to the new password anyway
    svc.lock()
    make_service().unlock(OTHER_MASTER, use_backup=True)


def test_failed_save_after_opening_backup_keeps_vault_and_retries(
    make_service: Factory, vault_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-H1: the final replace fails while quarantining: nothing is lost, the next save retries."""
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)
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


def test_non_ascii_master_password_nfc(make_service: Factory) -> None:
    composed = "caf\u00e9 cr\u00e8me fake passphrase"
    decomposed = "cafe\u0301 cre\u0300me fake passphrase"
    make_service().create(composed)
    make_service().unlock(decomposed)
    make_service().unlock(composed)


def test_lock_wipes_key_and_data(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)
    session = svc._session
    assert session is not None
    key = session.key
    svc.lock()
    assert not svc.is_unlocked
    assert key == bytearray(len(key))
    assert session.data.accounts == [] and session.data.games == []
    with pytest.raises(VaultLockedError):
        _ = svc.data
    with pytest.raises(VaultLockedError):
        svc.save()
    svc.lock()  # idempotent


def test_change_password(make_service: Factory, vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    _populate(svc)
    old_salt = vault_path.read_bytes()[22:38]
    svc.change_password(MASTER, OTHER_MASTER)
    assert vault_path.read_bytes()[22:38] != old_salt
    svc.lock()
    with pytest.raises(VaultAuthError):
        make_service().unlock(MASTER)
    fresh = make_service()
    fresh.unlock(OTHER_MASTER)
    assert len(fresh.data.accounts) == 1


def test_change_password_wrong_current_or_weak_new(make_service: Factory) -> None:
    delays: list[float] = []
    svc = make_service(sleep=delays.append, wrong_password_delay=0.5)
    svc.create(MASTER)
    with pytest.raises(VaultAuthError):
        svc.change_password("wrong fake passphrase", OTHER_MASTER)
    assert delays == [0.5]
    with pytest.raises(WeakPasswordError):
        svc.change_password(MASTER, "short")
    svc.lock()
    make_service().unlock(MASTER)  # unchanged


def test_change_password_upgrades_kdf(make_service: Factory) -> None:
    weak = KdfParams(1, 8192, 1)
    svc = make_service(kdf_params=weak)
    svc.create(MASTER)
    svc.lock()
    stronger = KdfParams(2, 16384, 1)
    upgraded = make_service(kdf_params=stronger)
    upgraded.unlock(MASTER)
    assert upgraded.kdf_needs_upgrade
    upgraded.change_password(MASTER, OTHER_MASTER)
    assert not upgraded.kdf_needs_upgrade


def test_failed_save_during_change_keeps_old_password(
    make_service: Factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = make_service()
    svc.create(MASTER)

    def fail(*_a: object, **_kw: object) -> None:
        raise VaultIOError("simulated")

    with monkeypatch.context() as patch, pytest.raises(VaultIOError):
        patch.setattr(vault_file, "write_vault_atomic", fail)
        svc.change_password(MASTER, OTHER_MASTER)
    svc.save()  # still works with the old key
    svc.lock()
    make_service().unlock(MASTER)


def test_async_api_with_inline_runner(make_service: Factory) -> None:
    events: list[str] = []
    errors: list[BaseException] = []
    svc = make_service(runner=InlineTaskRunner())
    svc.create_async(MASTER, lambda: events.append("created"), errors.append)
    svc.lock()
    svc.unlock_async("wrong fake passphrase", lambda: events.append("bad"), errors.append)
    svc.unlock_async(MASTER, lambda: events.append("unlocked"), errors.append)
    svc.change_password_async(MASTER, OTHER_MASTER, lambda: events.append("changed"),
                              errors.append)
    assert events == ["created", "unlocked", "changed"]
    assert len(errors) == 1 and isinstance(errors[0], VaultAuthError)


class DeferredRunner:
    """Captures tasks to prove the prepare step doesn't touch service state."""

    def __init__(self) -> None:
        self.pending: list[tuple[Any, Any, Any]] = []

    def submit(self, task: Any, on_success: Any, on_error: Any) -> None:
        self.pending.append((task, on_success, on_error))

    def run(self) -> None:
        """Run the latest task and deliver its result, like the real runners."""
        task, on_success, on_error = self.pending.pop()
        try:
            result = task()
        except Exception as exc:  # noqa: BLE001 - delivered like the real runners do
            on_error(exc)
            return
        on_success(result)


def test_prepare_step_does_not_mutate_state(make_service: Factory) -> None:
    make_service().create(MASTER)
    runner = DeferredRunner()
    svc = make_service(runner=runner)
    done: list[bool] = []
    svc.unlock_async(MASTER, lambda: done.append(True), lambda e: None)
    task, on_success, _ = runner.pending[0]
    result = task()  # "worker thread"
    assert not svc.is_unlocked  # nothing committed yet
    on_success(result)  # "UI thread"
    assert svc.is_unlocked and done == [True]


def test_unlock_cleans_stale_temp_files(make_service: Factory, vault_path: Path) -> None:
    make_service().create(MASTER)
    vault_file.tmp_path(vault_path).write_bytes(b"stale")
    make_service().unlock(MASTER)
    assert not vault_file.tmp_path(vault_path).exists()


def test_missing_vault(make_service: Factory) -> None:
    svc = make_service()
    assert not svc.exists()
    with pytest.raises(VaultIOError):
        svc.unlock(MASTER)


def test_fast_kdf_fixture_is_used(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    assert svc._session is not None and svc._session.kdf == FAST_KDF


# --- CR-L8: the change-password prepare step touches no service state ----------------------


def test_prepare_change_touches_no_service_state(make_service: Factory) -> None:
    """The worker step must not read the live session (it may be locked/wiped meanwhile)."""
    runner = DeferredRunner()
    svc = make_service(runner=runner)
    svc.create(MASTER)
    done: list[bool] = []
    svc.change_password_async(MASTER, OTHER_MASTER, lambda: done.append(True),
                              lambda exc: done.append(False))
    task, on_success, _on_error = runner.pending.pop()
    live = svc._session
    svc._session = None  # anything that reads the live session now fails
    try:
        result = task()  # the worker step
    finally:
        svc._session = live
    on_success(result)  # the commit step (caller's thread)
    assert done == [True]
    svc.lock()
    make_service().unlock(OTHER_MASTER)


def test_change_requested_before_a_lock_is_never_applied(make_service: Factory,
                                                         vault_path: Path) -> None:
    runner = DeferredRunner()
    svc = make_service(runner=runner)
    svc.create(MASTER)
    _populate(svc)
    before = vault_path.read_bytes()
    errors: list[BaseException] = []
    svc.change_password_async(MASTER, OTHER_MASTER, lambda: errors.append(AssertionError()),
                              errors.append)
    svc.lock()
    svc.unlock(MASTER)  # a new session before the old request finishes
    runner.run()
    assert len(errors) == 1 and isinstance(errors[0], VaultLockedError)
    assert vault_path.read_bytes() == before  # nothing written under the new password
    svc.lock()
    make_service().unlock(MASTER)


def test_change_still_works_without_interference(make_service: Factory) -> None:
    runner = DeferredRunner()
    svc = make_service(runner=runner)
    svc.create(MASTER)
    done: list[bool] = []
    svc.change_password_async(MASTER, OTHER_MASTER, lambda: done.append(True),
                              lambda exc: done.append(False))
    runner.run()
    assert done == [True]
    svc.lock()
    make_service().unlock(OTHER_MASTER)
