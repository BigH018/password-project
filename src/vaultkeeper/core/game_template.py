"""Per-game templates: rank ladder, regions, which standard fields show, and extra fields.

Every game carries its own template (stored in the vault). New games start from a starter:
one of the verified presets in ``config/constants.py`` or a blank template. Editing a
template never deletes account data: values no longer in the template are kept and shown
as "not in this game's list".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from vaultkeeper.config import constants as c


class FieldKind(StrEnum):
    """Type of an extra (user-defined) field."""

    TEXT = "text"
    NUMBER = "number"
    CHOICE = "choice"
    SECRET = "secret"  # noqa: S105 - a field type name. Masked, auto-cleared, never searched


# Standard fields a template may hide. The rest (name, login, password, email, status,
# labels, notes) always show.
OPTIONAL_FIELDS: tuple[str, ...] = (
    "tag", "region", "rank", "email_password", "email_login_url", "recovery_email",
)  # fmt: skip
MAX_DIVISIONS = 5
MAX_TIERS = 40
MAX_REGIONS = 40
MAX_CUSTOM_FIELDS = 20
MAX_CHOICES = 50
MAX_FIELD_LABEL = 40
MAX_EXTRA_VALUE = 500


@dataclass(frozen=True, slots=True)
class TierDef:
    """One rank tier and how many divisions it has (0 = none, e.g. Radiant)."""

    name: str
    divisions: int = 0


@dataclass(frozen=True, slots=True)
class CustomField:
    """A user-defined field. ``id`` is stable; the label can be renamed freely."""

    id: str
    label: str
    kind: FieldKind = FieldKind.TEXT
    choices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GameTemplate:
    """Everything that makes one game's accounts look the way the user wants."""

    tiers: tuple[TierDef, ...] = ()
    best_division_is_one: bool = False  # True: 1 is the top division (Overwatch, Rivals)
    roman_divisions: bool = False
    regions: tuple[str, ...] = ()
    hidden_fields: frozenset[str] = field(default_factory=frozenset)
    custom_fields: tuple[CustomField, ...] = ()

    def shows(self, field_name: str) -> bool:
        """Whether a standard field is shown for this game."""
        return field_name not in self.hidden_fields

    def custom_field(self, field_id: str) -> CustomField | None:
        """The extra field with this id, or None."""
        for custom in self.custom_fields:
            if custom.id == field_id:
                return custom
        return None

    @property
    def secret_field_ids(self) -> frozenset[str]:
        """Ids of extra fields holding secrets."""
        return frozenset(f.id for f in self.custom_fields if f.kind is FieldKind.SECRET)

    @property
    def searchable_field_ids(self) -> frozenset[str]:
        """Ids of extra fields that free-text search may look at (never secrets)."""
        return frozenset(f.id for f in self.custom_fields if f.kind is not FieldKind.SECRET)

    def to_preset(self) -> c.GamePreset:
        """This template's ladder and regions in the form the rank helpers use."""
        def divisions(count: int) -> tuple[int, ...]:
            low_to_high = range(count, 0, -1) if self.best_division_is_one else range(1, count + 1)
            return tuple(low_to_high)

        return c.GamePreset(
            key="template",
            label="",
            tiers=tuple(c.TierSpec(t.name, divisions(t.divisions)) for t in self.tiers),
            regions=self.regions,
            roman_divisions=self.roman_divisions,
        )


def template_from_preset(preset: c.GamePreset) -> GameTemplate:
    """A template copied from one of the built-in (verified) presets."""
    with_divisions = [t.divisions for t in preset.tiers if t.divisions]
    best_is_one = bool(with_divisions) and with_divisions[0][0] > with_divisions[0][-1]
    return GameTemplate(
        tiers=tuple(TierDef(t.name, len(t.divisions)) for t in preset.tiers),
        best_division_is_one=best_is_one,
        roman_divisions=preset.roman_divisions,
        regions=preset.regions,
    )


# Starters offered when adding a game. "blank" = no ranks or regions yet.
STARTERS: dict[str, str] = {
    c.VALORANT.key: c.VALORANT.label,
    c.MARVEL_RIVALS.key: c.MARVEL_RIVALS.label,
    c.OVERWATCH.key: c.OVERWATCH.label,
    "blank": "Blank (set up your own)",
}


def starter_template(key: str) -> GameTemplate:
    """Template for a starter key (unknown keys give a blank template)."""
    preset = c.PRESETS.get(key)
    if preset is None or preset.free_text:
        return GameTemplate()
    return template_from_preset(preset)
