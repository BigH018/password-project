"""Validation for game templates (as edited in Game setup) and for extra field values."""

from __future__ import annotations

import re
from typing import Any

from vaultkeeper.config import constants as c
from vaultkeeper.core.game_template import (
    MAX_CHOICES,
    MAX_CUSTOM_FIELDS,
    MAX_DIVISIONS,
    MAX_EXTRA_VALUE,
    MAX_FIELD_LABEL,
    MAX_REGIONS,
    MAX_TIERS,
    OPTIONAL_FIELDS,
    CustomField,
    FieldKind,
    GameTemplate,
    TierDef,
)
from vaultkeeper.core.text_validation import clean_secret, clean_text, clean_uuid
from vaultkeeper.errors import ValidationError

_NUMBER_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _unique_names(values: list[str], field: str, what: str) -> None:
    keys = [v.casefold() for v in values]
    if len(set(keys)) != len(keys):
        raise ValidationError(field, f"has the same {what} twice")


def clean_template(template: GameTemplate) -> GameTemplate:
    """Normalize a template or raise ValidationError (field names, never values)."""
    if len(template.tiers) > MAX_TIERS:
        raise ValidationError("ranks", f"at most {MAX_TIERS} ranks allowed")
    tiers = []
    for tier in template.tiers:
        name = clean_text(tier.name, "ranks", c.MAX_TIER, required=True)
        if not 0 <= tier.divisions <= MAX_DIVISIONS:
            raise ValidationError("ranks", f"divisions must be 0 to {MAX_DIVISIONS}")
        tiers.append(TierDef(name, tier.divisions))
    _unique_names([t.name for t in tiers], "ranks", "rank")

    if len(template.regions) > MAX_REGIONS:
        raise ValidationError("regions", f"at most {MAX_REGIONS} regions allowed")
    regions = [clean_text(r, "regions", c.MAX_REGION, required=True) for r in template.regions]
    _unique_names(regions, "regions", "region")

    if not set(template.hidden_fields) <= set(OPTIONAL_FIELDS):
        raise ValidationError("fields", "only optional standard fields can be hidden")
    if len(template.custom_fields) > MAX_CUSTOM_FIELDS:
        raise ValidationError("extra_fields", f"at most {MAX_CUSTOM_FIELDS} extra fields")
    fields = [_clean_custom_field(f) for f in template.custom_fields]
    _unique_names([f.label for f in fields], "extra_fields", "label")
    if len({f.id for f in fields}) != len(fields):
        raise ValidationError("extra_fields", "has a duplicate id")

    return GameTemplate(
        tiers=tuple(tiers),
        best_division_is_one=bool(template.best_division_is_one),
        roman_divisions=bool(template.roman_divisions),
        regions=tuple(regions),
        hidden_fields=frozenset(template.hidden_fields),
        custom_fields=tuple(fields),
    )


def _clean_custom_field(custom: CustomField) -> CustomField:
    label = clean_text(custom.label, "extra_fields", MAX_FIELD_LABEL, required=True)
    if not isinstance(custom.kind, FieldKind):
        raise ValidationError("extra_fields", "has an unknown type")
    choices: tuple[str, ...] = ()
    if custom.kind is FieldKind.CHOICE:
        if not custom.choices or len(custom.choices) > MAX_CHOICES:
            raise ValidationError("extra_fields", f"a dropdown needs 1 to {MAX_CHOICES} options")
        choices = tuple(clean_text(o, "extra_fields", MAX_FIELD_LABEL, required=True)
                        for o in custom.choices)
        _unique_names(list(choices), "extra_fields", "option")
    return CustomField(clean_uuid(custom.id, "extra_fields"), label, custom.kind, choices)


def clean_extra(
    extra: Any,
    template: GameTemplate,
    previous: tuple[tuple[str, str], ...] = (),
) -> tuple[tuple[str, str], ...]:
    """Validate extra field values against the template.

    Values for fields no longer in the template (or dropdown options since removed) are
    kept only if unchanged from ``previous``: nothing is deleted silently, and nothing new
    can be added to a field that doesn't exist. Empty values are dropped.
    """
    if not isinstance(extra, tuple):
        raise ValidationError("extra_fields", "has an invalid format")
    before = dict(previous)
    result: dict[str, str] = {}
    for item in extra:
        if not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str)):
            raise ValidationError("extra_fields", "has an invalid format")
        field_id, value = item
        custom = template.custom_field(field_id)
        label = custom.label if custom is not None else "extra field"
        if custom is None:
            if before.get(field_id) != value:
                raise ValidationError("extra_fields", "contains a field this game doesn't have")
            result[field_id] = value
            continue
        if custom.kind is FieldKind.SECRET:
            cleaned = clean_secret(value, label)
        else:
            cleaned = clean_text(value, label, MAX_EXTRA_VALUE)
        if not cleaned:
            continue
        if custom.kind is FieldKind.NUMBER and not _NUMBER_RE.match(cleaned):
            raise ValidationError(label, "must be a number")
        if (custom.kind is FieldKind.CHOICE and cleaned not in custom.choices
                and before.get(field_id) != cleaned):
            raise ValidationError(label, "is not one of this field's options")
        result[field_id] = cleaned
    return tuple(sorted(result.items()))
