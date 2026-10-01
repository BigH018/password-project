"""Vault service: changing the master password (re-encryption, .bak, locking meanwhile)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import MASTER, OTHER_MASTER
from vault_service_helpers import DeferredRunner, Factory, populate
from vaultkeeper.crypto.kdf import KdfParams
from vaultkeeper.errors import (
    VaultAuthError,
    VaultIOError,
    VaultLockedError,
    WeakPasswordError,
)
from vaultkeeper.storage import vault_file


def test_password_change_rotates_old_file_normally(make_service: Factory,
                                                    vault_path: Path) -> None:
    """The file on disk is still under the OLD password: that's not damage."""
    svc = make_service()
    svc.create(MASTER)
    populate(svc)
    svc.change_password(MASTER, OTHER_MASTER)
    assert svc.last_damaged_copy is None
    assert not list(vault_path.parent.glob("*.damaged-*"))


def test_password_change_resaves_bak_under_new_password(make_service: Factory,
                                                         vault_path: Path) -> None:
    """CR-M1/SEC-M1: after a change, .bak must not still open with the old password."""
    svc = make_service()
    svc.create(MASTER)
    populate(svc)
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
    populate(svc)

    def fail(*_a: object) -> None:
        raise VaultIOError("simulated")

    with monkeypatch.context() as patch:
        patch.setattr(vault_file, "copy_file_verified", fail)
        svc.change_password(MASTER, OTHER_MASTER)
    svc.save()  # the next normal save rotates .bak to the new password anyway
    svc.lock()
    make_service().unlock(OTHER_MASTER, use_backup=True)


def test_change_password(make_service: Factory, vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    populate(svc)
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
    populate(svc)
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
