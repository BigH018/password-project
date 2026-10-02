"""Game setup: add games and customise each one's ranks, regions and fields.

Changing a template never deletes account data (GameService.set_template); values that no
longer fit show as "not in this game's list" on the accounts. Unsaved edits are never
discarded silently: switching games or closing asks first (CR-L4).
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.game_template import STARTERS, GameTemplate, starter_template
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui import messages
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE
from vaultkeeper.ui.widgets.extra_fields_editor import ExtraFieldsEditor
from vaultkeeper.ui.widgets.field_toggles import FieldToggles
from vaultkeeper.ui.widgets.ladder_editor import LadderEditor

NEW_GAME = "+ New game"
RANKS_TAB, FIELDS_TAB = range(2)


class GameSetupDialog(QDialog):
    """``changed`` is True if anything was saved."""

    def __init__(self, games: GameService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._games = games
        self.changed = False
        self._loaded: tuple[str, GameTemplate] = ("", GameTemplate())  # editor as loaded
        self.setWindowTitle("Game setup")
        self.resize(960, 680)

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
        self.fields = FieldToggles(self)
        self.field_toggles = self.fields.boxes
        self.extras = ExtraFieldsEditor(self)
        self.regions_box = QGroupBox("Regions", self)
        self.extras_box = QGroupBox("Extra fields", self)
        self.tabs = QTabWidget(self)
        self.error_label = plain_label(parent=self)
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
        for model in (self.ladder.table.model(), self.extras.table.model()):
            model.rowsInserted.connect(self._update_tab_titles)
            model.rowsRemoved.connect(self._update_tab_titles)
        self.regions.textChanged.connect(self._update_tab_titles)
        self._reload()

    def _build_layout(self) -> None:
        starter_row = QHBoxLayout()
        starter_row.addWidget(self.starter, 1)
        starter_row.addWidget(self.starter_button)
        top = QFormLayout()
        top.addRow("Name", self.name)
        top.addRow("Start from", starter_row)

        self.regions.setToolTip("One region or server per line, in the order you want them")
        QVBoxLayout(self.regions_box).addWidget(self.regions)
        fields_box = QGroupBox("Standard fields shown", self)
        QVBoxLayout(fields_box).addWidget(self.fields)
        top_row = QHBoxLayout()
        top_row.addWidget(fields_box, 3)
        top_row.addWidget(self.regions_box, 2)
        QVBoxLayout(self.extras_box).addWidget(self.extras)
        fields_page = QWidget(self)
        fields_layout = QVBoxLayout(fields_page)
        fields_layout.addLayout(top_row)
        fields_layout.addWidget(self.extras_box, 1)
        self.tabs.addTab(self.ladder, "Ranks")
        self.tabs.addTab(fields_page, "Fields and regions")

        editor = QWidget(self)
        editor_layout = QVBoxLayout(editor)
        editor_layout.addLayout(top)
        editor_layout.addWidget(self.tabs, 1)
        editor_layout.addWidget(self.error_label)

        splitter = QSplitter(self)
        splitter.addWidget(self.list)
        splitter.addWidget(editor)
        splitter.setSizes([210, 750])
        buttons = QHBoxLayout()
        buttons.addWidget(self.delete_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)

    def _update_tab_titles(self, *_args: object) -> None:
        """Tab and box titles show how many ranks, regions and extra fields the game has."""
        regions = [line for line in self.regions.toPlainText().splitlines() if line.strip()]
        extras = self.extras.table.rowCount()
        self.tabs.setTabText(RANKS_TAB, f"Ranks ({self.ladder.table.rowCount()})")
        self.regions_box.setTitle(f"Regions ({len(regions)})")
        self.extras_box.setTitle(f"Extra fields ({extras})")

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
        self._show_selected()

    @property
    def has_changes(self) -> bool:
        """Whether the editor differs from the game as it was loaded (or a blank new game)."""
        return (self.name.text(), self.template()) != self._loaded

    def _discard_ok(self) -> bool:
        """True if there's nothing unsaved, or the user agrees to discard it."""
        return not self.has_changes or messages.confirm(
            self, "Discard changes?", "This game has unsaved changes. Discard them?",
            ok_text="Discard")

    def _selection_changed(self, current: QListWidgetItem | None = None,
                           previous: QListWidgetItem | None = None) -> None:
        if previous is not None and current is not previous and not self._discard_ok():
            self.list.blockSignals(True)  # stay on the edited game, edits kept
            self.list.setCurrentItem(previous)
            self.list.blockSignals(False)
            return
        self._show_selected()

    def _show_selected(self) -> None:
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
        self._loaded = (self.name.text(), self.template())  # read back: no false alarms

    # --- template <-> widgets ---------------------------------------------------------------

    def _load_template(self, template: GameTemplate) -> None:
        self.ladder.load(template)
        self.regions.setPlainText("\n".join(template.regions))
        self.fields.load(template)
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
            hidden_fields=self.fields.hidden(),
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

    # --- closing ----------------------------------------------------------------------------

    def accept(self) -> None:
        """Close button: asks before discarding unsaved edits."""
        if self._discard_ok():
            super().accept()

    def reject(self) -> None:
        """Esc / window close (Qt routes it here): asks before discarding unsaved edits."""
        if self._discard_ok():
            super().reject()

    def force_close(self) -> None:
        """Close without asking (used when the vault locks: edits are discarded)."""
        super().reject()

