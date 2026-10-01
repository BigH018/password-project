"""Schema v1 -> v2: presets become templates, custom games get ladders from their accounts."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from conftest import FAST_KDF, MASTER
from vaultkeeper.config import constants as c
from vaultkeeper.core import serialization as s
from vaultkeeper.core.game_template import GameTemplate, TierDef, template_from_preset
from vaultkeeper.core.migrations import migrate_v1_to_v2
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.crypto import envelope
from vaultkeeper.crypto.kdf import derive_key, new_salt
from vaultkeeper.errors import VaultFormatError

VAL_ID = "11111111-1111-4111-8111-111111111111"
APEX_ID = "22222222-2222-4222-8222-222222222222"
T = "2026-01-01T00:00:00+00:00"


def _account(n: int, game_id: str, tier: str | None, division: int | None,
             region: str | None) -> dict[str, Any]:
    return {
        "id": f"aaaaaaaa-aaaa-4aaa-8aaa-{n:012d}", "game_id": game_id,
        "display_name": f"FakeOld{n}", "tag": None, "login_username": f"old_login_{n}",
        "password": "Fake-Old-Pass-1", "email": f"old{n}@example.test", "email_password": None,
        "email_login_url": None, "region": region, "rank": {"tier": tier, "division": division},
        "status": "active", "recovery_email": None, "totp_secret": None, "tags": [],
        "notes": "", "created_at": T, "updated_at": T,
    }


def v1_payload() -> dict[str, Any]:
    """A schema-1 payload as Phases 1-4c wrote it."""
    return {
        "schema_version": 1,
        "games": [{"id": VAL_ID, "name": "Valorant", "preset": "valorant"},
                  {"id": APEX_ID, "name": "Apex", "preset": "custom"}],
        "accounts": [
            _account(1, VAL_ID, "Gold", 2, "EU"),
            _account(2, APEX_ID, "Diamond IV", None, "NA West"),
            _account(3, APEX_ID, "predator", None, "eu"),
            _account(4, APEX_ID, "Predator", None, None),
        ],
        "meta": {"created_at": T, "updated_at": T},
    }


def test_v1_payload_loads_as_v2() -> None:
    data = s.vault_from_dict(v1_payload())
    games = {g.name: g for g in data.games}
    assert games["Valorant"].template == template_from_preset(c.VALORANT)
    apex = games["Apex"].template
    assert apex.tiers == (TierDef("Diamond IV"), TierDef("predator"))  # distinct, first kept
    assert apex.regions == ("eu", "NA West")
    assert all(a.extra == () for a in data.accounts)
    assert data.accounts[1].rank.tier == "Diamond IV"  # account data untouched


def test_migration_does_not_touch_account_data() -> None:
    before = v1_payload()
    after = migrate_v1_to_v2(copy.deepcopy(before))
    for old, new in zip(before["accounts"], after["accounts"], strict=True):
        assert {k: v for k, v in new.items() if k != "extra"} == old
        assert new["extra"] == {}


def test_custom_game_without_accounts_gets_blank_template() -> None:
    raw = v1_payload()
    raw["accounts"] = [a for a in raw["accounts"] if a["game_id"] == VAL_ID]
    data = s.vault_from_dict(raw)
    assert next(g for g in data.games if g.name == "Apex").template == GameTemplate()


def test_malformed_v1_is_still_rejected() -> None:
    raw = v1_payload()
    raw["games"] = "not a list"
    with pytest.raises(VaultFormatError):
        s.vault_from_dict(raw)


def test_real_v1_vault_file_opens_and_resaves_as_v2(tmp_path: Path) -> None:
    """An encrypted v1 vault unlocks, and the next save writes schema 2."""
    path = tmp_path / "old.vault"
    salt = new_salt()
    key = derive_key(MASTER, salt, FAST_KDF)
    path.write_bytes(envelope.seal(json.dumps(v1_payload()).encode(), key, FAST_KDF, salt))

    svc = VaultService(path, kdf_params=FAST_KDF)
    svc.unlock(MASTER)
    assert len(svc.data.accounts) == 4
    svc.save()
    svc.lock()

    _hdr, _key, plaintext = envelope.open_with_password(path.read_bytes(), MASTER)
    saved = json.loads(plaintext)
    assert saved["schema_version"] == 2 and "template" in saved["games"][0]
    assert "preset" not in saved["games"][0]
