"""GameTemplate <-> JSON-safe dict, with strict structural checks (part of the vault payload).

Errors name the JSON path, never the value.
"""

from __future__ import annotations

import uuid
from typing import Any

from vaultkeeper.core.game_template import (
    MAX_DIVISIONS,
    OPTIONAL_FIELDS,
    CustomField,
    FieldKind,
    GameTemplate,
    TierDef,
)
from vaultkeeper.core.rank_image import image_from_text, image_to_text
from vaultkeeper.errors import VaultFormatError

_TEMPLATE_KEYS = frozenset({
    "tiers", "best_division_is_one", "roman_divisions", "regions", "hidden_fields",
    "custom_fields",
})  # fmt: skip
_TIER_KEYS = frozenset({"name", "divisions", "image"})
_FIELD_KEYS = frozenset({"id", "label", "kind", "choices"})


def _fail(path: str) -> VaultFormatError:
    return VaultFormatError(f"Vault payload is invalid ({path}).")


def template_to_dict(template: GameTemplate) -> dict[str, Any]:
    """Serialize a template."""
    return {
        "tiers": [_tier_to_dict(t) for t in template.tiers],
        "best_division_is_one": template.best_division_is_one,
        "roman_divisions": template.roman_divisions,
        "regions": list(template.regions),
        "hidden_fields": sorted(template.hidden_fields),
        "custom_fields": [
            {"id": f.id, "label": f.label, "kind": f.kind.value, "choices": list(f.choices)}
            for f in template.custom_fields
        ],
    }


def _tier_to_dict(tier: TierDef) -> dict[str, Any]:
    image = None if tier.image is None else image_to_text(tier.image)
    return {"name": tier.name, "divisions": tier.divisions, "image": image}


def _obj(value: Any, path: str, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _fail(path)
    return value


def _str_list(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise _fail(path)
    return tuple(value)


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise _fail(path)
    return value


def _tier(value: Any, path: str) -> TierDef:
    obj = _obj(value, path, _TIER_KEYS)
    divisions = obj["divisions"]
    if not isinstance(obj["name"], str):
        raise _fail(f"{path}.name")
    if (not isinstance(divisions, int) or isinstance(divisions, bool)
            or not 0 <= divisions <= MAX_DIVISIONS):
        raise _fail(f"{path}.divisions")
    image = None
    if obj["image"] is not None:
        image = image_from_text(obj["image"])
        if image is None:
            raise _fail(f"{path}.image")
    return TierDef(obj["name"], divisions, image)


def _field(value: Any, path: str) -> CustomField:
    obj = _obj(value, path, _FIELD_KEYS)
    field_id, label, kind = obj["id"], obj["label"], obj["kind"]
    if not isinstance(field_id, str):
        raise _fail(f"{path}.id")
    try:
        uuid.UUID(field_id)
    except ValueError:
        raise _fail(f"{path}.id") from None
    if not isinstance(label, str):
        raise _fail(f"{path}.label")
    try:
        parsed_kind = FieldKind(kind)
    except ValueError:
        raise _fail(f"{path}.kind") from None
    return CustomField(field_id, label, parsed_kind, _str_list(obj["choices"], f"{path}.choices"))


def template_from_dict(value: Any, path: str) -> GameTemplate:
    """Parse a template, raising VaultFormatError on any structural problem."""
    obj = _obj(value, path, _TEMPLATE_KEYS)
    if not isinstance(obj["tiers"], list):
        raise _fail(f"{path}.tiers")
    if not isinstance(obj["custom_fields"], list):
        raise _fail(f"{path}.custom_fields")
    hidden = _str_list(obj["hidden_fields"], f"{path}.hidden_fields")
    if not set(hidden) <= set(OPTIONAL_FIELDS):
        raise _fail(f"{path}.hidden_fields")
    fields = tuple(_field(f, f"{path}.custom_fields[{i}]")
                   for i, f in enumerate(obj["custom_fields"]))
    if len({f.id for f in fields}) != len(fields):
        raise _fail(f"{path}.custom_fields (duplicate id)")
    return GameTemplate(
        tiers=tuple(_tier(t, f"{path}.tiers[{i}]") for i, t in enumerate(obj["tiers"])),
        best_division_is_one=_bool(obj["best_division_is_one"], f"{path}.best_division_is_one"),
        roman_divisions=_bool(obj["roman_divisions"], f"{path}.roman_divisions"),
        regions=_str_list(obj["regions"], f"{path}.regions"),
        hidden_fields=frozenset(hidden),
        custom_fields=fields,
    )
