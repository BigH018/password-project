"""Accounts panel: game sidebar | (search bar over the sortable account table).

Filtering is done by ``core.search``; this widget only feeds it the UI's choices.
"""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.config.constants import DEFAULT_SHOW_PASSWORDS_SECONDS
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.models import Account
from vaultkeeper.core.search import facets, filter_accounts
from vaultkeeper.ui.widgets.account_table import AccountSortProxy, AccountTableModel
from vaultkeeper.ui.widgets.game_sidebar import GameSidebar
from vaultkeeper.ui.widgets.search_bar import SearchBar


class AccountsPanel(QWidget):
    """Shows accounts grouped by game with search and filters."""

    selection_changed = pyqtSignal()
    activated = pyqtSignal()  # double-click / Enter on a row
    reveal_expired = pyqtSignal()  # "Show passwords" has been on long enough

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._accounts: AccountService | None = None
        self._games: GameService | None = None
        self.shown = 0
        self.total = 0

        self.sidebar = GameSidebar(self)
        self.search = SearchBar(self)
        self.model = AccountTableModel(self)
        self.reveal_timer = QTimer(self)
        self.reveal_timer.setSingleShot(True)
        self.reveal_timer.setInterval(DEFAULT_SHOW_PASSWORDS_SECONDS * 1000)
        self.reveal_timer.timeout.connect(self.reveal_expired)
        self.proxy = AccountSortProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView(self)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.search)
        right_layout.addWidget(self.table, 1)
        splitter = QSplitter(self)
        splitter.addWidget(self.sidebar)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 900])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.sidebar.game_selected.connect(self._game_changed)
        self.search.changed.connect(self.refresh_rows)
        self.table.selectionModel().selectionChanged.connect(self.selection_changed)
        self.table.doubleClicked.connect(self.activated)

    # --- binding ----------------------------------------------------------------------------

    def bind(self, accounts: AccountService, games: GameService) -> None:
        """Attach to the unlocked vault's services and show everything."""
        self._accounts, self._games = accounts, games
        self.search.reset()
        self.refresh()
        self.sidebar.select_game(None)

    def clear(self) -> None:
        """Forget services and drop every row (used on lock)."""
        self._accounts = self._games = None
        self.model.clear()
        self.sidebar.clear()
        self.search.reset()
        self.shown = self.total = 0

    # --- refreshing -------------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild the sidebar counts and the rows (after any change)."""
        if self._accounts is None or self._games is None:
            return
        self.sidebar.set_games(self._games.list_games(), self._games.account_counts(),
                               len(self._accounts.list_all()))
        self._update_facets()
        self.refresh_rows()

    def _game_changed(self, _game_id: str | None) -> None:
        self._update_facets()
        self.refresh_rows()

    def _update_facets(self) -> None:
        if self._accounts is None or self._games is None:
            return
        game_id = self.sidebar.current_game_id()
        if game_id is None:
            self.search.set_facets(facets(self._accounts.list_all()))
        else:
            preset = self._games.get(game_id).rank_preset
            self.search.set_facets(facets(self._accounts.list_for_game(game_id), preset))

    def refresh_rows(self) -> None:
        """Re-run the filter and show the matching accounts."""
        if self._accounts is None or self._games is None:
            return
        game_id = self.sidebar.current_game_id()
        everything = self._accounts.list_all()
        games = {g.id: g for g in self._games.list_games()}
        searchable = frozenset().union(*(g.template.searchable_field_ids for g in games.values()))
        rows = filter_accounts(everything, self.search.build_filter(game_id), searchable)
        self.model.set_rows(rows, games, show_game=game_id is None,
                            single_game=games.get(game_id) if game_id else None)
        self.shown, self.total = len(rows), len(everything)
        self.selection_changed.emit()

    # --- selection & display ----------------------------------------------------------------

    def selected_account(self) -> Account | None:
        """The account in the selected row, if any."""
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.account_at(self.proxy.mapToSource(rows[0]).row())

    def select_account(self, account_id: str) -> bool:
        """Select the row showing ``account_id`` (if it's visible). Returns True if found."""
        for source_row in range(self.model.rowCount()):
            if self.model.account_at(source_row).id == account_id:
                proxy_index = self.proxy.mapFromSource(self.model.index(source_row, 0))
                self.table.selectRow(proxy_index.row())
                self.table.scrollTo(proxy_index)
                return True
        return False

    def set_reveal_seconds(self, seconds: int) -> None:
        """How long "Show passwords" stays on before switching itself off (SEC-Low6)."""
        self.reveal_timer.setInterval(seconds * 1000)

    def set_show_passwords(self, show: bool) -> None:
        """Reveal or mask the password column. Revealing starts the auto-hide timer."""
        self.model.set_show_passwords(show)
        if show:
            self.reveal_timer.start()
        else:
            self.reveal_timer.stop()
