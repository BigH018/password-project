"""Schema migrations for the vault payload: ``migrate_vN_to_vN+1`` functions, each tested.

Migrations work on the raw dict before strict parsing. They only transform shapes they
recognise; anything malformed is left for the strict parser to reject.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vaultkeeper.config.constants import PRESETS
from vaultkeeper.core.game_template import GameTemplate, TierDef, template_from_preset
from vaultkeeper.core.template_codec import template_to_dict


def _distinct(values: list[Any]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for value in values:
        if isinstance(value, str) and value.strip():
            seen.setdefault(value.casefold(), value)
    return tuple(sorted(seen.values(), key=str.casefold))


def _template_for_v1_game(preset_key: Any, accounts: list[dict[str, Any]]) -> GameTemplate:
    """Built-in presets are copied. Custom games get ranks/regions from their accounts."""
    preset = PRESETS.get(preset_key) if isinstance(preset_key, str) else None
    if preset is not None and not preset.free_text:
        return template_from_preset(preset)
    tiers = _distinct([(a.get("rank") or {}).get("tier") for a in accounts
                       if isinstance(a.get("rank"), dict)])
    regions = _distinct([a.get("region") for a in accounts])
    return GameTemplate(tiers=tuple(TierDef(t) for t in tiers), regions=regions)


def migrate_v1_to_v2(obj: dict[str, Any]) -> dict[str, Any]:
    """v2: games carry a full template instead of a preset key; accounts get ``extra``."""
    games, accounts = obj.get("games"), obj.get("accounts")
    if not isinstance(games, list) or not isinstance(accounts, list):
        return obj  # malformed: the strict parser will report it
    account_dicts = [a for a in accounts if isinstance(a, dict)]
    for game in games:
        if not isinstance(game, dict) or "preset" not in game:
            continue
        own = [a for a in account_dicts if a.get("game_id") == game.get("id")]
        game["template"] = template_to_dict(_template_for_v1_game(game.pop("preset"), own))
    for account in account_dicts:
        account.setdefault("extra", {})
    return obj


def migrate_v2_to_v3(obj: dict[str, Any]) -> dict[str, Any]:
    """v3: each rank in a game's template may carry a picture (``image``, null = none)."""
    games = obj.get("games")
    if not isinstance(games, list):
        return obj  # malformed: the strict parser will report it
    for game in games:
        template = game.get("template") if isinstance(game, dict) else None
        tiers = template.get("tiers") if isinstance(template, dict) else None
        for tier in tiers if isinstance(tiers, list) else ():
            if isinstance(tier, dict):
                tier.setdefault("image", None)
    return obj


# Keyed by the version they upgrade FROM.
MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: migrate_v1_to_v2,
    2: migrate_v2_to_v3,
}
