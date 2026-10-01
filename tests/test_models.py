"""Model invariants: immutability, ids, timestamps, and reprs that hide secrets/PII."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import datetime

import pytest

from fake_data import FAKE_PASSWORD, make_account, make_game
from vaultkeeper.core.models import SECRET_FIELDS, Account, Rank, VaultData, new_id, utc_now_iso


def test_new_id_is_unique_uuid4() -> None:
    ids = {new_id() for _ in range(100)}
    assert len(ids) == 100
    assert all(uuid.UUID(i).version == 4 for i in ids)


def test_utc_now_iso_is_timezone_aware() -> None:
    assert datetime.fromisoformat(utc_now_iso()).utcoffset() is not None


def test_account_is_immutable() -> None:
    account = make_account(make_game())
    with pytest.raises(dataclasses.FrozenInstanceError):
        account.password = "x"  # type: ignore[misc]


def test_account_repr_and_str_hide_secrets_and_pii() -> None:
    account = make_account(
        make_game(), email_password="Fake-Mail-Pass-9", totp_secret="JBSWY3DPEHPK3PXPJBSWY3DP"
    )
    for text in (repr(account), str(account), f"{account}"):
        assert account.id in text
        for value in (
            FAKE_PASSWORD, "Fake-Mail-Pass-9", "JBSWY3DPEHPK3PXPJBSWY3DP", account.email,
            account.login_username, account.display_name, account.recovery_email, account.notes,
        ):  # fmt: skip
            assert value not in text


def test_secret_fields_exist_on_account() -> None:
    names = {f.name for f in dataclasses.fields(Account)}
    assert set(SECRET_FIELDS) <= names
    for f in dataclasses.fields(Account):
        if f.name in SECRET_FIELDS:
            assert f.repr is False


def test_riot_id() -> None:
    game = make_game()
    assert make_account(game, display_name="Alt", tag="EUW").riot_id == "Alt#EUW"
    assert make_account(game, display_name="Alt", tag=None).riot_id == "Alt"


def test_rank_unranked() -> None:
    assert Rank().is_unranked
    assert not Rank("Gold", 1).is_unranked


def test_vault_repr_shows_counts_only() -> None:
    data = VaultData.empty()
    data.accounts.append(make_account(make_game()))
    assert repr(data) == "VaultData(games=0, accounts=1)"


def test_vault_empty_sets_timestamps() -> None:
    data = VaultData.empty()
    assert data.created_at and data.created_at == data.updated_at
