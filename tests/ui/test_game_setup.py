"""Game setup: add a custom game (ranks, regions, fields, extras), edit, starters, delete."""

from __future__ import annotations

from typing import Any

import pytest
from PyQt5.QtCore import Qt

from conftest import FakeStore
from fake_data import make_account
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.game_template import FieldKind, TierDef
from vaultkeeper.core.models import Rank
from vaultkeeper.ui import game_setup_dialog as gs


@pytest.fixture
def games(store: FakeStore) -> GameService:
    return GameService(store)


@pytest.fixture
def dialog(qtbot: Any, games: GameService) -> gs.GameSetupDialog:
    dlg = gs.GameSetupDialog(games)
    qtbot.addWidget(dlg)
    dlg.show()
    return dlg


def _type_rank(dialog: gs.GameSetupDialog, name: str, divisions: int) -> None:
    dialog.ladder.add_tier(name, divisions)


def _add_extra(dialog: gs.GameSetupDialog, label: str, kind: FieldKind,
               options: str = "") -> None:
    dialog.extras.add_field(None)
    row = dialog.extras.table.rowCount() - 1
    dialog.extras.table.item(row, 0).setText(label)
    box = dialog.extras.table.cellWidget(row, 1)
    box.setCurrentIndex(box.findData(kind))
    dialog.extras.table.item(row, 2).setText(options)


def test_new_game_starts_blank(dialog: gs.GameSetupDialog) -> None:
    assert dialog.list.item(0).text() == gs.NEW_GAME
    assert dialog.save_button.text() == "Add game"
    assert dialog.ladder.table.rowCount() == 0 and dialog.regions.toPlainText() == ""
    assert all(box.isChecked() for box in dialog.field_toggles.values())


def test_add_fortnite_with_custom_setup(dialog: gs.GameSetupDialog, games: GameService) -> None:
    dialog.name.setText("Fortnite")
    for name, divisions in (("Bronze", 3), ("Silver", 3), ("Elite", 0), ("Unreal", 0)):
        _type_rank(dialog, name, divisions)
    dialog.ladder.roman.setChecked(True)
    dialog.regions.setPlainText("EU\n  NA-East \n\nNA-West")
    dialog.field_toggles["tag"].setChecked(False)
    _add_extra(dialog, "Epic display name", FieldKind.TEXT)
    _add_extra(dialog, "Level", FieldKind.NUMBER)
    _add_extra(dialog, "Platform", FieldKind.CHOICE, "PC, PS5, Xbox")
    dialog.save_button.click()

    game = games.list_games()[0]
    t = game.template
    assert game.name == "Fortnite"
    assert t.tiers == (TierDef("Bronze", 3), TierDef("Silver", 3), TierDef("Elite"),
                       TierDef("Unreal"))
    assert t.regions == ("EU", "NA-East", "NA-West") and t.roman_divisions
    assert not t.shows("tag") and t.shows("rank")
    assert [(f.label, f.kind) for f in t.custom_fields] == [
        ("Epic display name", FieldKind.TEXT), ("Level", FieldKind.NUMBER),
        ("Platform", FieldKind.CHOICE)]
    assert t.custom_fields[2].choices == ("PC", "PS5", "Xbox")
    assert dialog.changed and dialog._selected_id() == game.id


def test_starter_fills_ranks_and_regions(dialog: gs.GameSetupDialog,
                                         games: GameService) -> None:
    dialog.name.setText("Overwatch 2")
    dialog.starter.setCurrentIndex(dialog.starter.findData("overwatch"))
    dialog.starter_button.click()
    assert dialog.ladder.tiers()[0] == TierDef("Bronze", 5)
    assert dialog.ladder.best_is_one.isChecked()
    assert dialog.regions.toPlainText().splitlines() == ["Americas", "Europe", "Asia"]
    dialog.save_button.click()
    assert games.list_games()[0].template.best_division_is_one


def test_invalid_setup_shows_error(dialog: gs.GameSetupDialog, games: GameService) -> None:
    dialog.name.setText("Broken")
    _type_rank(dialog, "Gold", 0)
    _type_rank(dialog, "gold", 0)
    dialog.save_button.click()
    assert "same rank twice" in dialog.error_label.text()
    assert games.list_games() == []
    dialog.ladder.table.selectRow(1)
    dialog.ladder.remove_button.click()
    _add_extra(dialog, "Platform", FieldKind.CHOICE, "")
    dialog.save_button.click()
    assert "dropdown needs" in dialog.error_label.text()


def test_reorder_ranks(dialog: gs.GameSetupDialog) -> None:
    for name in ("B", "A", "C"):
        _type_rank(dialog, name, 0)
    dialog.ladder.table.selectRow(1)
    dialog.ladder.up_button.click()
    assert [t.name for t in dialog.ladder.tiers()] == ["A", "B", "C"]
    dialog.ladder.down_button.click()
    assert [t.name for t in dialog.ladder.tiers()] == ["B", "A", "C"]


def test_edit_keeps_field_ids_and_account_data(dialog: gs.GameSetupDialog, games: GameService,
                                               store: FakeStore) -> None:
    dialog.name.setText("Fortnite")
    _type_rank(dialog, "Champion", 0)
    _add_extra(dialog, "Level", FieldKind.NUMBER)
    dialog.save_button.click()
    game = games.list_games()[0]
    level_id = game.template.custom_fields[0].id
    account = make_account(game, tag=None, region=None, rank=Rank("Champion", None),
                           extra=((level_id, "42"),))
    store.data.accounts.append(account)

    dialog._reload(select=game.id)
    dialog.extras.table.item(0, 0).setText("Account level")  # rename the field
    dialog.ladder.table.selectRow(0)
    dialog.ladder.remove_button.click()  # remove the rank the account uses
    dialog.save_button.click()

    updated = games.get(game.id).template
    assert updated.custom_fields[0].id == level_id  # same id: values stay linked
    assert updated.custom_fields[0].label == "Account level"
    assert updated.tiers == ()
    assert store.data.accounts == [account]  # never touched


def test_delete_rules(dialog: gs.GameSetupDialog, games: GameService, store: FakeStore,
                      monkeypatch: pytest.MonkeyPatch) -> None:
    used = games.add("Valorant", "valorant")
    empty = games.add("Empty")
    store.data.accounts.append(make_account(used))
    dialog._reload(select=used.id)
    dialog.delete_button.click()
    assert "still has 1 account" in dialog.error_label.text()
    dialog._reload(select=empty.id)
    dialog.delete_button.click()
    assert [g.name for g in games.list_games()] == ["Valorant"]
    assert dialog.list.currentItem().data(Qt.UserRole) is None  # back to "+ New game"


def test_add_rank_dialog_asks_about_divisions(qtbot: Any) -> None:
    from vaultkeeper.ui.widgets.add_rank_dialog import AddRankDialog

    added: list[tuple[str, int]] = []
    dialog = AddRankDialog(lambda name, div, _image: added.append((name, div)),
                           existing=["Gold"])
    qtbot.addWidget(dialog)
    dialog.show()
    assert not dialog.count.isEnabled()  # no divisions until ticked

    dialog.name.setText("Bronze")
    dialog.has_divisions.setChecked(True)
    dialog.count.setValue(3)
    dialog.add_button.click()
    assert added == [("Bronze", 3)]
    assert dialog.name.text() == "" and dialog.has_divisions.isChecked()  # ready for the next

    dialog.name.setText("Silver")
    qtbot.keyPress(dialog.name, Qt.Key_Return)  # Enter adds too
    dialog.has_divisions.setChecked(False)
    dialog.name.setText("Unreal")
    dialog.add_button.click()
    assert added == [("Bronze", 3), ("Silver", 3), ("Unreal", 0)]

    dialog.name.setText("gold")
    dialog.add_button.click()
    assert "already in the list" in dialog.error_label.text() and len(added) == 3
    dialog.name.setText("  ")
    dialog.add_button.click()
    assert "Type a rank name" in dialog.error_label.text()


def test_add_ranks_button_feeds_the_ladder(qtbot: Any, dialog: gs.GameSetupDialog,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    from vaultkeeper.ui.widgets import ladder_editor

    def fake_exec(self: Any) -> int:
        self.name.setText("Champion")
        self.has_divisions.setChecked(True)
        self.count.setValue(10)  # up to 10 divisions now
        self._add()
        return 1

    monkeypatch.setattr(ladder_editor.AddRankDialog, "exec_", fake_exec)
    dialog.ladder.add_button.click()
    assert dialog.ladder.tiers() == [TierDef("Champion", 10)]


# --- CR-L4: unsaved edits are never discarded silently -------------------------------------


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"titles": [], "answer": False}

    def fake_confirm(_parent: Any, title: str, *_a: Any, **_k: Any) -> bool:
        state["titles"].append(title)
        return state["answer"]

    monkeypatch.setattr(gs.messages, "confirm", fake_confirm)
    return state


def _two_games(games: GameService) -> tuple[str, str]:
    first = games.add("Fake Game One", starter_template_blank()).id
    second = games.add("Fake Game Two", starter_template_blank()).id
    return first, second


def starter_template_blank() -> Any:
    from vaultkeeper.core.game_template import GameTemplate

    return GameTemplate()


def _select(dialog: gs.GameSetupDialog, game_id: str | None) -> None:
    for row in range(dialog.list.count()):
        if dialog.list.item(row).data(Qt.UserRole) == game_id:
            dialog.list.setCurrentRow(row)
            return
    raise AssertionError("game not in the list")


def test_switching_games_asks_before_discarding(qtbot: Any, games: GameService,
                                                asked: dict[str, Any]) -> None:
    first, second = _two_games(games)
    dlg = gs.GameSetupDialog(games)
    qtbot.addWidget(dlg)
    _select(dlg, first)
    assert asked["titles"] == []  # nothing edited yet
    dlg.name.setText("Fake Game One Renamed")
    _select(dlg, second)
    assert asked["titles"] == ["Discard changes?"]
    assert dlg.list.currentItem().data(Qt.UserRole) == first  # stayed on the edited game
    assert dlg.name.text() == "Fake Game One Renamed"  # edit kept
    asked["answer"] = True
    _select(dlg, second)
    assert dlg.list.currentItem().data(Qt.UserRole) == second
    assert games.get(first).name == "Fake Game One"  # discarded, never saved


def test_close_asks_before_discarding(qtbot: Any, games: GameService,
                                      asked: dict[str, Any]) -> None:
    first, _second = _two_games(games)
    dlg = gs.GameSetupDialog(games)
    qtbot.addWidget(dlg)
    dlg.show()
    _select(dlg, first)
    dlg.regions.setPlainText("EU")
    dlg.close_button.click()
    assert asked["titles"] == ["Discard changes?"] and dlg.isVisible()
    dlg.reject()  # Esc / window close
    assert len(asked["titles"]) == 2 and dlg.isVisible()
    asked["answer"] = True
    dlg.close_button.click()
    assert not dlg.isVisible()


def test_saved_or_untouched_games_never_ask(qtbot: Any, games: GameService,
                                            asked: dict[str, Any]) -> None:
    first, second = _two_games(games)
    dlg = gs.GameSetupDialog(games)
    qtbot.addWidget(dlg)
    dlg.show()
    _select(dlg, first)
    dlg.name.setText("Fake Game One Renamed")
    dlg.save_button.click()
    _select(dlg, second)
    dlg.close_button.click()
    assert asked["titles"] == [] and not dlg.isVisible()


def test_force_close_never_asks(qtbot: Any, games: GameService, asked: dict[str, Any]) -> None:
    dlg = gs.GameSetupDialog(games)
    qtbot.addWidget(dlg)
    dlg.show()
    dlg.name.setText("Half-typed fake game")
    dlg.force_close()
    assert asked["titles"] == [] and not dlg.isVisible()
