"""Manage games: add, rename, change preset, delete (blocked rules come from GameService)."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.config.constants import DEFAULT_PRESET_KEY, PRESETS
from vaultkeeper.core.game_service import GameService
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui import messages
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE


class GameManagerDialog(QDialog):
    """List of games with an edit area. ``changed`` is True if anything was saved."""

    def __init__(self, games: GameService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._games = games
        self.changed = False
        self.setWindowTitle("Manage games")
        self.setMinimumWidth(460)

        self.list = QListWidget(self)
        self.name = QLineEdit(self)
        self.name.setPlaceholderText("Game name")
        self.preset = QComboBox(self)
        for preset in PRESETS.values():
            label = "Custom (type rank and region freely)" if preset.free_text else preset.label
            self.preset.addItem(label, preset.key)
        hint = QLabel("A game's preset sets its rank ladder and regions.", self)
        hint.setStyleSheet(MUTED_STYLE)
        self.error_label = QLabel(self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.add_button = QPushButton("Add as new game", self)
        self.save_button = QPushButton("Save changes", self)
        self.delete_button = QPushButton("Delete", self)
        self.close_button = QPushButton("Close", self)

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Preset", self.preset)
        actions = QHBoxLayout()
        actions.addWidget(self.add_button)
        actions.addWidget(self.save_button)
        actions.addWidget(self.delete_button)
        actions.addStretch(1)
        actions.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addLayout(form)
        layout.addWidget(hint)
        layout.addWidget(self.error_label)
        layout.addLayout(actions)

        self.list.currentItemChanged.connect(self._selection_changed)
        self.add_button.clicked.connect(self._add)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)
        self.close_button.clicked.connect(self.accept)
        self._reload()
        self.name.setFocus()

    def _selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _reload(self, select: str | None = None) -> None:
        counts = self._games.account_counts()
        self.list.blockSignals(True)
        self.list.clear()
        for game in self._games.list_games():
            preset = PRESETS[game.preset].label if game.preset in PRESETS else "Custom"
            item = QListWidgetItem(
                f"{game.name}  ({counts.get(game.id, 0)} accounts, {preset})")
            item.setData(Qt.UserRole, game.id)
            self.list.addItem(item)
            if game.id == select:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self, *_args: object) -> None:
        game_id = self._selected_id()
        self.save_button.setEnabled(game_id is not None)
        self.delete_button.setEnabled(game_id is not None)
        if game_id is None:
            self.preset.setCurrentIndex(self.preset.findData(DEFAULT_PRESET_KEY))
            return
        game = self._games.get(game_id)
        self.name.setText(game.name)
        self.preset.setCurrentIndex(max(self.preset.findData(game.preset), 0))
        self.error_label.clear()

    def _run(self, action: str, fn: Callable[[], object]) -> bool:
        try:
            fn()
        except VaultKeeperError as exc:
            self.error_label.setText(f"Could not {action}: {messages.error_text(exc)}")
            return False
        self.error_label.clear()
        self.changed = True
        return True

    def _add(self) -> None:
        created: list[str] = []
        if self._run("add the game",
                     lambda: created.append(self._games.add(self.name.text(),
                                                            self.preset.currentData()).id)):
            self._reload(select=created[0])

    def _save(self) -> None:
        game_id = self._selected_id()
        if game_id is None:
            return
        game = self._games.get(game_id)
        if self.name.text().strip() != game.name and not self._run(
                "rename the game", lambda: self._games.rename(game_id, self.name.text())):
            return
        if self.preset.currentData() != game.preset and not self._run(
                "change the preset", lambda: self._games.set_preset(game_id,
                                                                     self.preset.currentData())):
            error = self.error_label.text()
            self._reload(select=game_id)  # shows the stored preset again...
            self.error_label.setText(error)  # ...but keeps the explanation visible
            return
        self._reload(select=game_id)

    def _delete(self) -> None:
        game_id = self._selected_id()
        if game_id is None:
            return
        name = self._games.get(game_id).name
        if not messages.confirm(self, "Delete game", f"Delete the game {name}?", ok_text="Delete"):
            return
        if self._run("delete the game", lambda: self._games.delete(game_id)):
            self.name.clear()
            self._reload()
