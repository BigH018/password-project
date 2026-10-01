"""Payload round trip, schema versioning and rejection of malformed input."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from fake_data import make_account, make_game
from vaultkeeper.core import serialization as s
from vaultkeeper.core.models import SCHEMA_VERSION, Rank, VaultData
from vaultkeeper.errors import VaultFormatError


def _dict(data: VaultData) -> dict[str, Any]:
    return json.loads(s.dumps_payload(data))


def test_round_trip(fake_vault: VaultData) -> None:
    restored = s.loads_payload(s.dumps_payload(fake_vault))
    assert restored == fake_vault


def test_round_trip_optional_and_unicode_fields() -> None:
    data = VaultData.empty()
    game = make_game("Overwatch", "overwatch")
    data.games.append(game)
    data.accounts.append(make_account(
        game, display_name="Joueur\u00e9\U0001f3ae", tag=None, email_password="Fake-Mail-1",
        email_login_url=None, region=None, rank=Rank(), recovery_email=None,
        totp_secret="JBSWY3DPEHPK3PXP", tags=(), notes="",
    ))
    assert s.loads_payload(s.dumps_payload(data)) == data


def test_payload_includes_schema_version(fake_vault: VaultData) -> None:
    assert _dict(fake_vault)["schema_version"] == SCHEMA_VERSION


def test_values_outside_the_template_still_load(fake_vault: VaultData) -> None:
    """Editing a game's template must never stop a vault from opening."""
    gone = "00000000-0000-4000-8000-000000000000"
    raw = _dict(fake_vault)
    raw["games"][0]["template"]["tiers"] = []
    raw["accounts"][0]["rank"] = {"tier": "Renamed Tier", "division": 9}
    raw["accounts"][0]["region"] = "Old Region"
    raw["accounts"][0]["extra"] = {gone: "kept value"}
    loaded = s.vault_from_dict(raw)
    assert loaded.accounts[0].rank.tier == "Renamed Tier"
    assert loaded.accounts[0].extra_value(gone) == "kept value"


def test_newer_schema_refused(fake_vault: VaultData) -> None:
    raw = _dict(fake_vault)
    raw["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(VaultFormatError, match="newer version"):
        s.vault_from_dict(raw)


@pytest.mark.parametrize("version", [0, -1, "1", None, True, 1.0])
def test_bad_schema_version(fake_vault: VaultData, version: Any) -> None:
    raw = _dict(fake_vault)
    raw["schema_version"] = version
    with pytest.raises(VaultFormatError):
        s.vault_from_dict(raw)


def test_migration_chain_runs_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a future schema v3: v1 payloads go through 1->2 then 2->3."""
    calls: list[int] = []

    def step(obj: dict[str, Any]) -> dict[str, Any]:
        calls.append(obj["schema_version"])
        return {**obj, f"migrated_from_{obj['schema_version']}": True}

    monkeypatch.setattr(s, "SCHEMA_VERSION", 3)
    monkeypatch.setitem(s.MIGRATIONS, 1, step)
    monkeypatch.setitem(s.MIGRATIONS, 2, step)
    result = s.migrate({"schema_version": 1})
    assert calls == [1, 2]
    assert result["schema_version"] == 3
    assert result["migrated_from_1"] and result["migrated_from_2"]


def test_missing_migration_step_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(s, "SCHEMA_VERSION", SCHEMA_VERSION + 1)
    with pytest.raises(VaultFormatError, match="No migration"):
        s.migrate({"schema_version": SCHEMA_VERSION})


BAD_FIELD = {"id": "00000000-0000-4000-8000-000000000000", "label": "L",
             "kind": "colour", "choices": []}


def _mutations() -> list[tuple[str, Any]]:
    def drop(path: list[Any]) -> Any:
        def f(raw: dict[str, Any]) -> None:
            target = raw
            for key in path[:-1]:
                target = target[key]
            del target[path[-1]]
        return f

    def setv(path: list[Any], value: Any) -> Any:
        def f(raw: dict[str, Any]) -> None:
            target = raw
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
        return f

    return [
        ("missing games", drop(["games"])),
        ("extra top key", setv(["extra"], 1)),
        ("games not list", setv(["games"], {})),
        ("game extra key", setv(["games", 0, "x"], 1)),
        ("game bad id", setv(["games", 0, "id"], "nope")),
        ("game missing template", drop(["games", 0, "template"])),
        ("template extra key", setv(["games", 0, "template", "x"], 1)),
        ("divisions too big", setv(["games", 0, "template", "tiers", 0, "divisions"], 11)),
        ("divisions bool", setv(["games", 0, "template", "tiers", 0, "divisions"], True)),
        ("hidden core field", setv(["games", 0, "template", "hidden_fields"], ["password"])),
        ("bad field kind", setv(["games", 0, "template", "custom_fields"], [BAD_FIELD])),
        ("extra not dict", setv(["accounts", 0, "extra"], [])),
        ("extra value not str", setv(["accounts", 0, "extra"], {"a": 1})),
        ("account missing field", drop(["accounts", 0, "password"])),
        ("account unknown field", setv(["accounts", 0, "level"], 30)),
        ("password not str", setv(["accounts", 0, "password"], 123)),
        ("bad status", setv(["accounts", 0, "status"], "deleted")),
        ("bad game ref", setv(["accounts", 0, "game_id"], "00000000-0000-4000-8000-000000000000")),
        ("naive timestamp", setv(["accounts", 0, "created_at"], "2026-01-01T00:00:00")),
        ("bad timestamp", setv(["meta", "updated_at"], "yesterday")),
        ("division bool", setv(["accounts", 0, "rank", "division"], True)),
        ("division str", setv(["accounts", 0, "rank", "division"], "2")),
        ("unranked with division", setv(["accounts", 0, "rank"], {"tier": None, "division": 1})),
        ("tags not list", setv(["accounts", 0, "tags"], "a,b")),
        ("tag not str", setv(["accounts", 0, "tags"], [1])),
    ]


@pytest.mark.parametrize(("name", "mutate"), _mutations(), ids=[m[0] for m in _mutations()])
def test_malformed_payload_rejected(fake_vault: VaultData, name: str, mutate: Any) -> None:
    raw = copy.deepcopy(_dict(fake_vault))
    mutate(raw)
    with pytest.raises(VaultFormatError):
        s.vault_from_dict(raw)


def test_duplicate_ids_rejected(fake_vault: VaultData) -> None:
    raw = _dict(fake_vault)
    raw["accounts"][1]["id"] = raw["accounts"][0]["id"]
    with pytest.raises(VaultFormatError):
        s.vault_from_dict(raw)
    raw = _dict(fake_vault)
    raw["games"][1]["id"] = raw["games"][0]["id"]
    with pytest.raises(VaultFormatError):
        s.vault_from_dict(raw)


@pytest.mark.parametrize(
    "payload",
    [b"\xff\xfe", b"not json", b"[]", b'{"a":1,"a":2}', b'{"schema_version": NaN}', b""],
)
def test_bad_bytes_rejected(payload: bytes) -> None:
    with pytest.raises(VaultFormatError):
        s.loads_payload(payload)


def test_error_messages_do_not_leak_values(fake_vault: VaultData) -> None:
    raw = _dict(fake_vault)
    raw["accounts"][0]["status"] = "fake-secret-status"
    with pytest.raises(VaultFormatError) as info:
        s.vault_from_dict(raw)
    assert "fake-secret-status" not in str(info.value)
    assert "accounts[0].status" in str(info.value)
