"""VaultData <-> JSON payload, with strict structural checks and schema migrations.

Loading checks *structure* (types, ids, references, timestamps, statuses) and rejects unknown
keys, because silently dropping them would lose data on the next save. It deliberately does
NOT check ranks or regions against the current presets: if a game renames a tier, old vaults
must still open. Preset rules are applied when an account is edited (core/validation.py).

Error messages name the JSON path (e.g. ``accounts[3].status``), never the value.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from vaultkeeper.config.constants import STATUSES
from vaultkeeper.core.models import SCHEMA_VERSION, Account, Game, Rank, VaultData
from vaultkeeper.errors import VaultFormatError

# migrate_vN_to_vN+1 functions, keyed by the version they upgrade FROM.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {}

_TOP_KEYS = frozenset({"schema_version", "games", "accounts", "meta"})
_META_KEYS = frozenset({"created_at", "updated_at"})
_GAME_KEYS = frozenset({"id", "name", "preset"})
_RANK_KEYS = frozenset({"tier", "division"})
_ACCOUNT_STR = (
    "id", "game_id", "display_name", "login_username", "password", "email", "status",
    "notes", "created_at", "updated_at",
)  # fmt: skip
_ACCOUNT_OPT_STR = (
    "tag", "email_password", "email_login_url", "region", "recovery_email", "totp_secret",
)  # fmt: skip
_ACCOUNT_KEYS = frozenset((*_ACCOUNT_STR, *_ACCOUNT_OPT_STR, "rank", "tags"))


def _fail(path: str) -> VaultFormatError:
    return VaultFormatError(f"Vault payload is invalid ({path}).")


# --- Encoding ---------------------------------------------------------------------------------


def _account_to_dict(account: Account) -> dict[str, Any]:
    out: dict[str, Any] = {name: getattr(account, name) for name in _ACCOUNT_STR}
    out.update({name: getattr(account, name) for name in _ACCOUNT_OPT_STR})
    out["rank"] = {"tier": account.rank.tier, "division": account.rank.division}
    out["tags"] = list(account.tags)
    return out


def vault_to_dict(data: VaultData) -> dict[str, Any]:
    """Convert VaultData to a JSON-safe dict (current schema version)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "games": [{"id": g.id, "name": g.name, "preset": g.preset} for g in data.games],
        "accounts": [_account_to_dict(a) for a in data.accounts],
        "meta": {"created_at": data.created_at, "updated_at": data.updated_at},
    }


def dumps_payload(data: VaultData) -> bytes:
    """Serialize VaultData to compact UTF-8 JSON bytes."""
    text = json.dumps(
        vault_to_dict(data), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return text.encode("utf-8")


# --- Decoding helpers -------------------------------------------------------------------------


def _obj(value: Any, path: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _fail(path)
    return value


def _str(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise _fail(path)
    return value


def _opt_str(value: Any, path: str) -> str | None:
    return None if value is None else _str(value, path)


def _uuid(value: Any, path: str) -> str:
    text = _str(value, path)
    try:
        if str(uuid.UUID(text)) != text:
            raise _fail(path)
    except ValueError:
        raise _fail(path) from None
    return text


def _timestamp(value: Any, path: str) -> str:
    text = _str(value, path)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise _fail(path) from None
    if parsed.tzinfo is None:
        raise _fail(path)
    return text


def _rank(value: Any, path: str) -> Rank:
    obj = _obj(value, path, _RANK_KEYS)
    tier = _opt_str(obj["tier"], f"{path}.tier")
    division = obj["division"]
    if division is not None and (not isinstance(division, int) or isinstance(division, bool)):
        raise _fail(f"{path}.division")
    if tier is None and division is not None:
        raise _fail(path)
    return Rank(tier=tier, division=division)


def _tags(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _fail(path)
    return tuple(_str(item, f"{path}[{i}]") for i, item in enumerate(value))


def _game(value: Any, path: str) -> Game:
    obj = _obj(value, path, _GAME_KEYS)
    return Game(
        id=_uuid(obj["id"], f"{path}.id"),
        name=_str(obj["name"], f"{path}.name"),
        preset=_str(obj["preset"], f"{path}.preset"),
    )


def _account(value: Any, path: str) -> Account:
    obj = _obj(value, path, _ACCOUNT_KEYS)
    fields: dict[str, Any] = {n: _str(obj[n], f"{path}.{n}") for n in _ACCOUNT_STR}
    fields.update({n: _opt_str(obj[n], f"{path}.{n}") for n in _ACCOUNT_OPT_STR})
    for name in ("id", "game_id"):
        _uuid(fields[name], f"{path}.{name}")
    for name in ("created_at", "updated_at"):
        _timestamp(fields[name], f"{path}.{name}")
    if fields["status"] not in STATUSES:
        raise _fail(f"{path}.status")
    return Account(**fields, rank=_rank(obj["rank"], f"{path}.rank"),
                   tags=_tags(obj["tags"], f"{path}.tags"))


# --- Decoding ---------------------------------------------------------------------------------


def migrate(obj: dict[str, Any]) -> dict[str, Any]:
    """Upgrade a payload dict to the current schema version, step by step."""
    version = obj.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise _fail("schema_version")
    if version > SCHEMA_VERSION:
        raise VaultFormatError("This vault was created by a newer version of VaultKeeper.")
    while version < SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise VaultFormatError(f"No migration available from schema version {version}.")
        obj = step(obj)
        version += 1
        obj["schema_version"] = version
    return obj


def vault_from_dict(raw: Any) -> VaultData:
    """Build VaultData from a parsed payload, migrating and validating structure."""
    if not isinstance(raw, dict):
        raise _fail("root")
    obj = _obj(migrate(raw), "root", _TOP_KEYS)
    meta = _obj(obj["meta"], "meta", _META_KEYS)
    if not isinstance(obj["games"], list):
        raise _fail("games")
    if not isinstance(obj["accounts"], list):
        raise _fail("accounts")

    games = [_game(g, f"games[{i}]") for i, g in enumerate(obj["games"])]
    accounts = [_account(a, f"accounts[{i}]") for i, a in enumerate(obj["accounts"])]

    game_ids = [g.id for g in games]
    if len(set(game_ids)) != len(game_ids):
        raise _fail("games (duplicate id)")
    account_ids = [a.id for a in accounts]
    if len(set(account_ids)) != len(account_ids):
        raise _fail("accounts (duplicate id)")
    known = set(game_ids)
    for i, account in enumerate(accounts):
        if account.game_id not in known:
            raise _fail(f"accounts[{i}].game_id")

    return VaultData(
        games=games,
        accounts=accounts,
        created_at=_timestamp(meta["created_at"], "meta.created_at"),
        updated_at=_timestamp(meta["updated_at"], "meta.updated_at"),
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VaultFormatError("Vault payload is invalid (duplicate key).")
        result[key] = value
    return result


def _reject_constant(_name: str) -> Any:
    raise VaultFormatError("Vault payload is invalid (non-finite number).")


def loads_payload(raw: bytes) -> VaultData:
    """Parse UTF-8 JSON payload bytes into VaultData."""
    try:
        text = raw.decode("utf-8")
        obj = json.loads(
            text, object_pairs_hook=_reject_duplicate_keys, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise VaultFormatError("Vault payload is not valid JSON.") from None
    return vault_from_dict(obj)
