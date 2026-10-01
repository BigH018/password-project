"""Game manager dialog: add, rename, preset change rules, delete rules (counts shown)."""

from __future__ import annotations

from typing import Any

import pytest

from conftest import FakeStore
from fake_data import make_account
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.models import Rank
from vaultkeeper.ui import game_manager_dialog as gm


@pytest.fixture
def games(store: FakeStore) -> GameService:
    return GameService(store)


@pytest.fixture
def dialog(qtbot: Any, games: GameService) -> gm.GameManagerDialog:
    dlg = gm.GameManagerDialog(games)
    qtbot.addWidget(dlg)
    dlg.show()
    return dlg


def _add(dialog: gm.GameManagerDialog, name: str, preset: str) -> None:
    dialog.list.setCurrentRow(-1)
    dialog.name.setText(name)
    dialog.preset.setCurrentIndex(dialog.preset.findData(preset))
    dialog.add_button.click()


def test_add_games(dialog: gm.GameManagerDialog, games: GameService) -> None:
    _add(dialog, "Valorant", "valorant")
    _add(dialog, "Apex Legends", "custom")
    assert [g.name for g in games.list_games()] == ["Apex Legends", "Valorant"]
    assert dialog.changed and dialog.list.count() == 2
    assert "0 accounts, Valorant" in dialog.list.item(1).text()


def test_duplicate_name_message(dialog: gm.GameManagerDialog) -> None:
    _add(dialog, "Valorant", "valorant")
    _add(dialog, "valorant", "valorant")
    assert "already exists" in dialog.error_label.text()


def test_rename(dialog: gm.GameManagerDialog, games: GameService) -> None:
    _add(dialog, "Valornt", "valorant")
    dialog.list.setCurrentRow(0)
    dialog.name.setText("Valorant")
    dialog.save_button.click()
    assert games.list_games()[0].name == "Valorant"


def test_preset_change_blocked_with_count(dialog: gm.GameManagerDialog, games: GameService,
                                         store: FakeStore) -> None:
    _add(dialog, "Valorant", "valorant")
    game = games.list_games()[0]
    store.data.accounts.extend([make_account(game, n=1, rank=Rank("Ascendant", 1)),
                                make_account(game, n=2, rank=Rank("Radiant", None))])
    dialog.list.setCurrentRow(0)
    dialog.preset.setCurrentIndex(dialog.preset.findData("overwatch"))
    dialog.save_button.click()
    assert "2 accounts would become invalid" in dialog.error_label.text()
    assert games.get(game.id).preset == "valorant"
    assert dialog.preset.currentData() == "valorant"  # dropdown snaps back to the stored preset


def test_delete_rules(dialog: gm.GameManagerDialog, games: GameService, store: FakeStore,
                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gm.messages, "confirm", lambda *_a, **_k: True)
    _add(dialog, "Valorant", "valorant")
    _add(dialog, "Empty", "custom")
    valorant = next(g for g in games.list_games() if g.name == "Valorant")
    store.data.accounts.append(make_account(valorant))

    dialog._reload(select=valorant.id)
    dialog.delete_button.click()
    assert "still has 1 account" in dialog.error_label.text()
    assert len(games.list_games()) == 2

    empty = next(g for g in games.list_games() if g.name == "Empty")
    dialog._reload(select=empty.id)
    dialog.delete_button.click()
    assert [g.name for g in games.list_games()] == ["Valorant"]


def test_delete_cancelled(dialog: gm.GameManagerDialog, games: GameService,
                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gm.messages, "confirm", lambda *_a, **_k: False)
    _add(dialog, "Valorant", "valorant")
    dialog.list.setCurrentRow(0)
    dialog.delete_button.click()
    assert len(games.list_games()) == 1
