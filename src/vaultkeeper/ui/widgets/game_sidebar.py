"""Game list with account counts. "All games" is always the first entry."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QListWidget, QListWidgetItem

from vaultkeeper.core.models import Game


class GameSidebar(QListWidget):
    """Emits ``game_selected`` with a game id, or None for All games."""

    game_selected = pyqtSignal(object)

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(170)
        self.currentItemChanged.connect(self._emit_current)
        self._updating = False

    def set_games(self, games: list[Game], counts: dict[str, int], total: int) -> None:
        """Rebuild the list, keeping the current selection when that game still exists."""
        keep = self.current_game_id()
        self._updating = True
        try:
            self.clear()
            self._add(f"All games ({total})", None)
            for game in games:
                self._add(f"{game.name} ({counts.get(game.id, 0)})", game.id)
            target = 0
            for row in range(self.count()):
                if self.item(row).data(Qt.UserRole) == keep:
                    target = row
            self.setCurrentRow(target)
        finally:
            self._updating = False

    def _add(self, label: str, game_id: str | None) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, game_id)
        self.addItem(item)

    def current_game_id(self) -> str | None:
        """Selected game id, or None for All games / nothing."""
        item = self.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def select_game(self, game_id: str | None) -> None:
        """Select a game by id (None = All games)."""
        for row in range(self.count()):
            if self.item(row).data(Qt.UserRole) == game_id:
                self.setCurrentRow(row)
                return

    def _emit_current(self, *_args: Any) -> None:
        if not self._updating:
            self.game_selected.emit(self.current_game_id())
