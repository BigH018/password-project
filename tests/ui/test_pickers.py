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


# --- CR-M2: switching game on the account form --------------------------------------------


def _form(qtbot: Any, account: Any, games: list[Any]) -> Any:
    from vaultkeeper.ui.widgets.account_form import AccountForm

    form = AccountForm(games)
    qtbot.addWidget(form)
    form.load(account)
    return form


def _pick(form: Any, game: Any) -> None:
    form.game.setCurrentIndex(form.game.findData(game.id))


def _marked(form: Any) -> bool:
    texts = _texts(form.rank.tier) + _texts(form.region.combo)
    return any(NOT_IN_LIST in t for t in texts)


def test_switching_game_resets_values_the_new_game_lacks(qtbot: Any) -> None:
    from fake_data import make_account, make_game

    val, ow = make_game("Valorant", "valorant"), make_game("Overwatch", "overwatch")
    form = _form(qtbot, make_account(val, rank=Rank("Ascendant", 2), region="EU"), [val, ow])
    _pick(form, ow)
    assert form.rank.rank() == Rank() and form.region.region() is None
    assert not _marked(form)
    saved = form.to_account(make_account(val))
    assert saved.rank == Rank() and saved.region is None


def test_switching_game_keeps_values_both_games_have(qtbot: Any) -> None:
    from fake_data import make_account, make_game

    val, ow = make_game("Valorant", "valorant"), make_game("Overwatch", "overwatch")
    form = _form(qtbot, make_account(val, rank=Rank("Gold", 2), region="EU"), [val, ow])
    _pick(form, ow)
    assert form.rank.rank() == Rank("Gold", 2)


def test_own_games_unlisted_values_come_back_only_there(qtbot: Any) -> None:
    from fake_data import make_account, make_game

    val, ow = make_game("Valorant", "valorant"), make_game("Overwatch", "overwatch")
    account = make_account(val, rank=Rank("Old Tier", None), region="Moon Base")
    form = _form(qtbot, account, [val, ow])
    assert form.rank.tier.currentText() == "Old Tier" + NOT_IN_LIST
    _pick(form, ow)
    assert form.rank.rank() == Rank() and form.region.region() is None
    assert not _marked(form)
    _pick(form, val)  # back to the account's own game: stored values shown again
    assert form.rank.rank() == Rank("Old Tier", None)
    assert form.region.region() == "Moon Base"
