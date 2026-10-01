"""Vault lifecycle: create, unlock, wrong password, tamper, save, lock, change password, async."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import FAST_KDF, MASTER, OTHER_MASTER
from vault_service_helpers import DeferredRunner, Factory, populate
from vaultkeeper.core.tasks import InlineTaskRunner
from vaultkeeper.errors import (
    VaultAuthError,
    VaultFormatError,
    VaultIOError,
    VaultLockedError,
    WeakPasswordError,
)


def test_create_then_unlock_round_trip(make_service: Factory, vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    assert svc.is_unlocked and vault_path.exists()
    populate(svc)
    saved = (list(svc.data.games), list(svc.data.accounts))
    svc.lock()

    again = make_service()
    again.unlock(MASTER)
    assert (again.data.games, again.data.accounts) == saved


def test_file_contains_no_plaintext(make_service: Factory, vault_path: Path) -> None:
    svc = make_service()
    svc.create(MASTER)
    populate(svc)
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
    populate(svc)
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






















def test_non_ascii_master_password_nfc(make_service: Factory) -> None:
    composed = "caf\u00e9 cr\u00e8me fake passphrase"
    decomposed = "cafe\u0301 cre\u0300me fake passphrase"
    make_service().create(composed)
    make_service().unlock(decomposed)
    make_service().unlock(composed)


def test_lock_wipes_key_and_data(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    populate(svc)
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




def test_missing_vault(make_service: Factory) -> None:
    svc = make_service()
    assert not svc.exists()
    with pytest.raises(VaultIOError):
        svc.unlock(MASTER)


def test_fast_kdf_fixture_is_used(make_service: Factory) -> None:
    svc = make_service()
    svc.create(MASTER)
    assert svc._session is not None and svc._session.kdf == FAST_KDF








