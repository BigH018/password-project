"""Game setup: add games and customise each one's ranks, regions and fields.

Changing a template never deletes account data (GameService.set_template); values that no
longer fit show as "not in this game's list" on the accounts.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.game_template import OPTIONAL_FIELDS, STARTERS, GameTemplate, starter_template
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui import messages
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE
from vaultkeeper.ui.widgets.extra_fields_editor import ExtraFieldsEditor
from vaultkeeper.ui.widgets.ladder_editor import LadderEditor

FIELD_LABELS = {
    "tag": "Tag (#)", "region": "Region", "rank": "Rank", "email_password": "Email password",
    "email_login_url": "Email login URL", "recovery_email": "Recovery email",
}  # fmt: skip
NEW_GAME = "+ New game"


class GameSetupDialog(QDialog):
    """``changed`` is True if anything was saved."""

    def __init__(self, games: GameService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._games = games
        self.changed = False
        self.setWindowTitle("Game setup")
        self.resize(900, 640)

        self.list = QListWidget(self)
        self.name = QLineEdit(self)
        self.name.setPlaceholderText("e.g. Fortnite")
        self.starter = QComboBox(self)
        for key, label in STARTERS.items():
            self.starter.addItem(label, key)
        self.starter_button = QPushButton("Fill from starter", self)
        self.ladder = LadderEditor(self)
        self.regions = QPlainTextEdit(self)
        self.regions.setPlaceholderText("One region per line, e.g.\nEU\nNA-East")
        self.field_toggles = {key: QCheckBox(label, self) for key, label in FIELD_LABELS.items()}
        self.extras = ExtraFieldsEditor(self)
        self.error_label = QLabel(self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.save_button = QPushButton("Save game", self)
        self.save_button.setDefault(True)
        self.delete_button = QPushButton("Delete game", self)
        self.close_button = QPushButton("Close", self)
        self._build_layout()

        self.list.currentItemChanged.connect(self._selection_changed)
        self.starter_button.clicked.connect(self._fill_from_starter)
        self.save_button.clicked.connect(self._save)
        self.delete_button.clicked.connect(self._delete)
        self.close_button.clicked.connect(self.accept)
        self._reload()

    def _build_layout(self) -> None:
        starter_row = QHBoxLayout()
        starter_row.addWidget(self.starter, 1)
        starter_row.addWidget(self.starter_button)
        top = QFormLayout()
        top.addRow("Name", self.name)
        top.addRow("Start from", starter_row)

        ranks_box = QGroupBox("Ranks", self)
        QVBoxLayout(ranks_box).addWidget(self.ladder)
        regions_box = QGroupBox("Regions", self)
        QVBoxLayout(regions_box).addWidget(self.regions)
        fields_box = QGroupBox("Standard fields shown", self)
        grid = QGridLayout(fields_box)
        for i, box in enumerate(self.field_toggles.values()):
            grid.addWidget(box, i // 3, i % 3)
        always = QLabel("Always shown: name, login, password, email, status, labels, notes.", self)
        always.setStyleSheet(MUTED_STYLE)
        grid.addWidget(always, 2, 0, 1, 3)
        extras_box = QGroupBox("Extra fields", self)
        QVBoxLayout(extras_box).addWidget(self.extras)

        middle = QHBoxLayout()
        middle.addWidget(ranks_box, 3)
        middle.addWidget(regions_box, 1)
        editor = QWidget(self)
        editor_layout = QVBoxLayout(editor)
        editor_layout.addLayout(top)
        editor_layout.addLayout(middle, 2)
        editor_layout.addWidget(fields_box)
        editor_layout.addWidget(extras_box, 1)
        editor_layout.addWidget(self.error_label)

        splitter = QSplitter(self)
        splitter.addWidget(self.list)
        splitter.addWidget(editor)
        splitter.setSizes([200, 700])
        buttons = QHBoxLayout()
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)

    # --- list -------------------------------------------------------------------------------

    def _selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _reload(self, select: str | None = None) -> None:
        counts = self._games.account_counts()
        self.list.blockSignals(True)
        self.list.clear()
        new_item = QListWidgetItem(NEW_GAME)
        new_item.setData(Qt.UserRole, None)
        self.list.addItem(new_item)
        target = new_item
        for game in self._games.list_games():
            item = QListWidgetItem(f"{game.name} ({counts.get(game.id, 0)})")
            item.setData(Qt.UserRole, game.id)
            self.list.addItem(item)
            if game.id == select:
                target = item
        self.list.setCurrentItem(target)
        self.list.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self, *_args: object) -> None:
        game_id = self._selected_id()
        self.error_label.clear()
        self.delete_button.setEnabled(game_id is not None)
        self.save_button.setText("Add game" if game_id is None else "Save game")
        if game_id is None:
            self.name.clear()
            self.starter.setCurrentIndex(self.starter.findData("blank"))
            self._load_template(GameTemplate())
            self.name.setFocus()
        else:
            game = self._games.get(game_id)
            self.name.setText(game.name)
            self._load_template(game.template)

    # --- template <-> widgets ---------------------------------------------------------------

    def _load_template(self, template: GameTemplate) -> None:
        self.ladder.load(template)
        self.regions.setPlainText("\n".join(template.regions))
        for key, box in self.field_toggles.items():
            box.setChecked(template.shows(key))
        self.extras.load(template.custom_fields)

    def _fill_from_starter(self) -> None:
        """Replace ranks and regions with the chosen starter (fields and extras untouched)."""
        starter = starter_template(self.starter.currentData())
        current = self.template()
        self.ladder.load(starter)
        self.regions.setPlainText("\n".join(starter.regions))
        self.extras.load(current.custom_fields)

    def template(self) -> GameTemplate:
        """The template described by the editor right now (validated on save)."""
        lines = (line.strip() for line in self.regions.toPlainText().splitlines())
        return GameTemplate(
            tiers=tuple(self.ladder.tiers()),
            best_division_is_one=self.ladder.best_is_one.isChecked(),
            roman_divisions=self.ladder.roman.isChecked(),
            regions=tuple(line for line in lines if line),
            hidden_fields=frozenset(k for k in OPTIONAL_FIELDS
                                    if not self.field_toggles[k].isChecked()),
            custom_fields=tuple(self.extras.fields()),
        )

    # --- actions ----------------------------------------------------------------------------

    def _run(self, action: str, fn: Callable[[], object]) -> bool:
        """Run a service call; show a generic error and return False if it fails."""
        try:
            fn()
        except VaultKeeperError as exc:
            self.error_label.setText(f"Could not {action}: {messages.error_text(exc)}")
            return False
        self.changed = True
        return True

    def _save(self) -> None:
        game_id = self._selected_id()
        template = self.template()
        if game_id is None:
            created: list[str] = []
            if self._run("add the game", lambda: created.append(
                    self._games.add(self.name.text(), template).id)):
                self._reload(select=created[0])
            return
        current = self._games.get(game_id)
        if self.name.text().strip() != current.name and not self._run(
                "rename the game", lambda: self._games.rename(game_id, self.name.text())):
            return
        if self._run("save the game", lambda: self._games.set_template(game_id, template)):
            self._reload(select=game_id)

    def _delete(self) -> None:
        game_id = self._selected_id()
        if game_id is None:
            return
        name = self._games.get(game_id).name
        if not messages.confirm(self, "Delete game", f"Delete the game {name}?", ok_text="Delete"):
            return
        if self._run("delete the game", lambda: self._games.delete(game_id)):
            self._reload()
