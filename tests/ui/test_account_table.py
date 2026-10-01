"""Account table model: the rank preset is built once per game, not per cell or comparison."""

from __future__ import annotations

from typing import Any

import pytest
from PyQt5.QtCore import Qt

from fake_data import make_account, make_game
from vaultkeeper.core.game_template import GameTemplate
from vaultkeeper.core.models import Rank
from vaultkeeper.ui.widgets.account_table import AccountTableModel


def test_rank_preset_is_built_once_per_game(qapp: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    val, ow = make_game("Valorant", "valorant"), make_game("Overwatch", "overwatch")
    accounts = [make_account(val if n % 2 else ow, n, rank=Rank("Gold", 2)) for n in range(200)]
    calls: list[int] = []
    real = GameTemplate.to_preset
    monkeypatch.setattr(GameTemplate, "to_preset",
                        lambda self: calls.append(1) or real(self))
    model = AccountTableModel()
    model.set_rows(accounts, {val.id: val, ow.id: ow}, show_game=True)
    rank = model.column_of("rank")
    labels = [model.data(model.index(row, rank), Qt.DisplayRole)
              for row in range(model.rowCount())]
    keys = [model.sort_key(row, rank) for row in range(model.rowCount())]
    assert "Gold 2" in labels and len(keys) == 200
    assert len(calls) <= 2  # once per game, not once per cell / comparison
