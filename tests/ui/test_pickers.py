"""Rank and region pickers follow the game's preset; legacy values are kept, not dropped."""

from __future__ import annotations

from typing import Any

import pytest

from vaultkeeper.config import constants as c
from vaultkeeper.core.models import Rank
from vaultkeeper.ui.widgets.rank_picker import NOT_IN_LIST, RankPicker, RegionPicker


@pytest.fixture
def rank(qtbot: Any) -> RankPicker:
    picker = RankPicker()
    qtbot.addWidget(picker)
    return picker


@pytest.fixture
def region(qtbot: Any) -> RegionPicker:
    picker = RegionPicker()
    qtbot.addWidget(picker)
    return picker


def _texts(combo: Any) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def test_tiers_follow_preset(rank: RankPicker) -> None:
    rank.set_preset(c.VALORANT, keep=Rank())
    assert _texts(rank.tier)[0] == c.UNRANKED_LABEL
    assert _texts(rank.tier)[1:] == list(c.VALORANT.tier_names)
    assert not rank.division.isEnabled()


def test_divisions_follow_tier_highest_first(rank: RankPicker) -> None:
    rank.set_preset(c.OVERWATCH, keep=Rank("Gold", 3))
    assert _texts(rank.division) == ["-", "1", "2", "3", "4", "5"]
    assert rank.rank() == Rank("Gold", 3)
    rank.tier.setCurrentIndex(rank.tier.findData("Top 500"))
    assert not rank.division.isEnabled() and rank.rank() == Rank("Top 500", None)


def test_marvel_rivals_roman_divisions(rank: RankPicker) -> None:
    rank.set_preset(c.MARVEL_RIVALS, keep=Rank("Diamond", 2))
    assert _texts(rank.division) == ["-", "I", "II", "III"]
    assert rank.division.currentText() == "II"


def test_division_optional(rank: RankPicker) -> None:
    rank.set_preset(c.VALORANT, keep=Rank("Gold", None))
    assert rank.division.isEnabled() and rank.rank() == Rank("Gold", None)


def test_free_text_preset(rank: RankPicker) -> None:
    rank.set_preset(c.CUSTOM, keep=Rank("Diamond IV", None))
    assert rank.free_text and rank.free.text() == "Diamond IV"
    rank.free.setText("  ")
    assert rank.rank() == Rank()


def test_legacy_tier_is_shown_not_dropped(rank: RankPicker) -> None:
    rank.set_preset(c.VALORANT, keep=Rank("Old Tier", None))
    assert rank.tier.currentText() == "Old Tier" + NOT_IN_LIST
    assert rank.rank() == Rank("Old Tier", None)


def test_switching_presets_keeps_compatible_values(rank: RankPicker) -> None:
    rank.set_preset(c.VALORANT, keep=Rank("Gold", 2))
    rank.set_preset(c.OVERWATCH)  # Gold 2 also exists in Overwatch
    assert rank.rank() == Rank("Gold", 2)


def test_region_picker(region: RegionPicker) -> None:
    region.set_preset(c.VALORANT, keep="EU")
    assert _texts(region.combo) == ["(none)", *c.VALORANT.regions]
    assert region.region() == "EU"
    region.set_region(None)
    assert region.region() is None
    region.set_preset(c.CUSTOM, keep="NA West")
    assert region.region() == "NA West"


def test_region_legacy_value_kept(region: RegionPicker) -> None:
    region.set_preset(c.OVERWATCH, keep="EU")
    assert region.combo.currentText() == "EU" + NOT_IN_LIST and region.region() == "EU"
