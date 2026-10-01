"""Preset consistency and rank formatting."""

from __future__ import annotations

import pytest

from vaultkeeper.config import constants as c


@pytest.mark.parametrize("preset", list(c.PRESETS.values()), ids=lambda p: p.key)
def test_preset_is_consistent(preset: c.GamePreset) -> None:
    names = preset.tier_names
    assert names and len(set(names)) == len(names)
    assert preset.regions and len(set(preset.regions)) == len(preset.regions)
    for spec in preset.tiers:
        assert len(spec.name) <= c.MAX_TIER
        assert len(set(spec.divisions)) == len(spec.divisions)
        assert all(d > 0 for d in spec.divisions)
    for region in preset.regions:
        assert len(region) <= c.MAX_REGION
    assert c.PRESETS[preset.key] is preset


def test_valorant_ladder() -> None:
    p = c.VALORANT
    assert p.tier_names[0] == "Iron" and p.tier_names[-1] == "Radiant"
    assert p.tier("Immortal").divisions == (1, 2, 3)
    assert not p.tier("Radiant").has_divisions
    assert "Ascendant" in p.tier_names


def test_marvel_rivals_ladder() -> None:
    p = c.MARVEL_RIVALS
    assert p.tier_names[-2:] == ("Eternity", "One Above All")
    assert p.tier("Celestial").divisions == (3, 2, 1)
    assert not p.tier("Eternity").has_divisions
    assert p.roman_divisions


def test_overwatch_ladder_divisions_run_5_to_1() -> None:
    p = c.OVERWATCH
    assert p.tier("Bronze").divisions == (5, 4, 3, 2, 1)
    assert p.tier("Champion").divisions == (5, 4, 3, 2, 1)
    assert not p.tier("Top 500").has_divisions
    assert p.tier_names.index("Master") < p.tier_names.index("Grandmaster")


def test_status_values() -> None:
    assert c.STATUSES == ("active", "banned", "locked", "retired")
    assert c.DEFAULT_STATUS in c.STATUSES


def test_get_preset_falls_back_to_custom() -> None:
    assert c.get_preset("valorant") is c.VALORANT
    assert c.get_preset("no-such-game") is c.CUSTOM


@pytest.mark.parametrize(
    ("preset", "tier", "division", "expected"),
    [
        (c.VALORANT, "Platinum", 2, "Platinum 2"),
        (c.VALORANT, "Radiant", None, "Radiant"),
        (c.MARVEL_RIVALS, "Gold", 2, "Gold II"),
        (c.OVERWATCH, "Diamond", 5, "Diamond 5"),
        (c.VALORANT, None, None, "Unranked"),
        (c.VALORANT, "Gold", None, "Gold"),
    ],
)
def test_format_rank(preset: c.GamePreset, tier: str | None, division: int | None,
                     expected: str) -> None:
    assert c.format_rank(preset, tier, division) == expected
