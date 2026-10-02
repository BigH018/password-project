"""Rank pictures shown: accounts table (Rank column), rank picker, search rank filter."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox

from conftest import FakeStore
from fake_data import make_account, make_game, tiny_png
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.game_template import TierDef
from vaultkeeper.core.models import Game, Rank, VaultData
from vaultkeeper.core.search import facets
from vaultkeeper.ui.accounts_view import AccountsPanel
from vaultkeeper.ui.rank_pictures import tier_icons
from vaultkeeper.ui.widgets.account_form import AccountForm
from vaultkeeper.ui.widgets.account_table import AccountTableModel
from vaultkeeper.ui.widgets.rank_picker import RankPicker
from vaultkeeper.ui.widgets.search_bar import SearchBar


def _pictured(game: Game, *pictured: str) -> Game:
    """``game`` with a picture on the named tiers."""
    tiers = tuple(TierDef(t.name, t.divisions, tiny_png() if t.name in pictured else None)
                  for t in game.template.tiers)
    return replace(game, template=replace(game.template, tiers=tiers))


def _has_icon(box: QComboBox, data: Any) -> bool:
    return not box.itemIcon(box.findData(data)).isNull()


def test_tier_icons_only_for_pictured_ranks(qapp: Any) -> None:
    icons = tier_icons(_pictured(make_game(), "Gold", "Radiant").template)
    assert set(icons) == {"Gold", "Radiant"}
    assert all(not icon.isNull() for icon in icons.values())


def test_table_shows_the_picture_in_the_rank_column(qapp: Any) -> None:
    val = _pictured(make_game("Valorant", "valorant"), "Gold")
    ow = make_game("Overwatch", "overwatch")  # also has Gold, without a picture
    rows = [make_account(val, 1, rank=Rank("Gold", 2)), make_account(val, 2, rank=Rank()),
            make_account(val, 3, rank=Rank("Iron", 1)), make_account(ow, 4, rank=Rank("Gold"))]
    model = AccountTableModel()
    model.set_rows(rows, {val.id: val, ow.id: ow}, show_game=True)
    rank, name = model.column_of("rank"), model.column_of("name")
    icons = [model.data(model.index(r, rank), Qt.DecorationRole) for r in range(4)]
    assert [icon is not None and not icon.isNull() for icon in icons] == [
        True, False, False, False]
    assert model.data(model.index(0, rank), Qt.DisplayRole) == "Gold 2"  # text stays
    assert model.data(model.index(0, name), Qt.DecorationRole) is None
    model.clear()  # lock
    assert model.rowCount() == 0


def test_rank_picker_shows_pictures(qapp: Any) -> None:
    game = _pictured(make_game(), "Gold")
    picker = RankPicker()
    picker.set_preset(game.rank_preset, keep=Rank("Old Tier"), icons=tier_icons(game.template))
    assert _has_icon(picker.tier, "Gold")
    assert not _has_icon(picker.tier, "Iron") and not _has_icon(picker.tier, None)
    assert not _has_icon(picker.tier, "Old Tier")  # the "not in list" entry
    picker.set_preset(game.rank_preset)  # no icons given: none shown
    assert not _has_icon(picker.tier, "Gold")


def test_account_form_rank_picker_uses_the_game_pictures(qtbot: Any) -> None:
    pictured = _pictured(make_game("Valorant", "valorant"), "Gold")
    plain = make_game("Overwatch", "overwatch")
    form = AccountForm([pictured, plain])
    qtbot.addWidget(form)
    form.load(make_account(pictured, rank=Rank("Gold", 1)))
    assert _has_icon(form.rank.tier, "Gold")
    form.game.setCurrentIndex(form.game.findData(plain.id))  # switch game
    assert not _has_icon(form.rank.tier, "Gold")


def test_search_rank_filter_shows_pictures(qapp: Any) -> None:
    game = _pictured(make_game(), "Gold")
    accounts = [make_account(game, 1, rank=Rank("Gold", 1)),
                make_account(game, 2, rank=Rank("Iron", 1))]
    bar = SearchBar()
    bar.set_facets(facets(accounts, game.rank_preset), tier_icons(game.template))
    assert _has_icon(bar.rank, "Gold") and not _has_icon(bar.rank, "Iron")
    bar.set_facets(facets(accounts, game.rank_preset))
    assert not _has_icon(bar.rank, "Gold")


def test_panel_filter_pictures_only_for_one_selected_game(qtbot: Any) -> None:
    val = _pictured(make_game("Valorant", "valorant"), "Gold")
    ow = make_game("Overwatch", "overwatch")  # "Gold" here too: All games stays text only
    data = VaultData(games=[val, ow], accounts=[make_account(val, 1, rank=Rank("Gold", 1)),
                                                make_account(ow, 2, rank=Rank("Gold", 1))])
    store = FakeStore(data)
    panel = AccountsPanel()
    qtbot.addWidget(panel)
    panel.bind(AccountService(store), GameService(store))
    panel.sidebar.select_game(val.id)
    assert _has_icon(panel.search.rank, "Gold")
    panel.sidebar.select_game(ow.id)
    assert not _has_icon(panel.search.rank, "Gold")
    panel.sidebar.select_game(None)
    assert not _has_icon(panel.search.rank, "Gold")
