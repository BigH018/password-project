"""Account table: model with masked passwords, plus a proxy that sorts with proper keys."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from vaultkeeper.config.constants import get_preset
from vaultkeeper.core.models import Account, Game
from vaultkeeper.core.search import rank_label, rank_sort_key

MASK = chr(0x2022) * 8  # bullet characters; built with chr() to keep the source ASCII-only

# (key, header). "game" is only shown in the All games view.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("game", "Game"),
    ("name", "Name#Tag"),
    ("login", "Login"),
    ("email", "Email"),
    ("password", "Password"),
    ("rank", "Rank"),
    ("region", "Region"),
    ("status", "Status"),
    ("tags", "Tags"),
    ("updated", "Updated"),
)


class AccountTableModel(QAbstractTableModel):
    """Read-only rows of accounts. Passwords are masked unless ``show_passwords`` is on."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[Account] = []
        self._games: dict[str, Game] = {}
        self._columns = COLUMNS
        self._show_passwords = False

    # --- data in ------------------------------------------------------------------------

    def set_rows(self, accounts: list[Account], games: dict[str, Game], show_game: bool) -> None:
        """Replace all rows. ``games`` maps game id to Game (for names and presets)."""
        self.beginResetModel()
        self._rows = list(accounts)
        self._games = dict(games)
        self._columns = COLUMNS if show_game else tuple(c for c in COLUMNS if c[0] != "game")
        self.endResetModel()

    def clear(self) -> None:
        """Drop every row (used on lock)."""
        self.set_rows([], {}, show_game=True)

    @property
    def show_passwords(self) -> bool:
        """Whether the password column shows clear text."""
        return self._show_passwords

    def set_show_passwords(self, show: bool) -> None:
        """Reveal or mask the password column."""
        self._show_passwords = show
        if self._rows:
            col = self.column_of("password")
            self.dataChanged.emit(self.index(0, col), self.index(len(self._rows) - 1, col))

    # --- lookups ------------------------------------------------------------------------

    def column_of(self, key: str) -> int:
        """Index of a column key in the current layout (-1 if hidden)."""
        keys = [c[0] for c in self._columns]
        return keys.index(key) if key in keys else -1

    def account_at(self, row: int) -> Account:
        """The account shown in ``row`` of this (source) model."""
        return self._rows[row]

    def _value(self, account: Account, key: str) -> str:
        game = self._games.get(account.game_id)
        if key == "game":
            return game.name if game else ""
        if key == "name":
            return account.riot_id
        if key == "login":
            return account.login_username
        if key == "email":
            return account.email
        if key == "password":
            if not account.password:
                return ""
            return account.password if self._show_passwords else MASK
        if key == "rank":
            return rank_label(account, get_preset(game.preset if game else ""))
        if key == "region":
            return account.region or ""
        if key == "status":
            return account.status.capitalize()
        if key == "tags":
            return ", ".join(account.tags)
        if key == "updated":
            return account.updated_at[:10]
        return ""

    def sort_key(self, row: int, column: int) -> Any:
        """Comparable key for sorting. Never derived from a secret."""
        account, key = self._rows[row], self._columns[column][0]
        if key == "password":
            return ""
        if key == "rank":
            game = self._games.get(account.game_id)
            return rank_sort_key(account, get_preset(game.preset if game else ""))
        if key == "updated":
            return account.updated_at
        return self._value(account, key).casefold()

    # --- Qt model API -------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._columns)

    def headerData(self, section: int, orientation: Qt.Orientation,  # noqa: N802
                   role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self._columns[section][1]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        return self._value(self._rows[index.row()], self._columns[index.column()][0])


class AccountSortProxy(QSortFilterProxyModel):
    """Sorts using ``AccountTableModel.sort_key`` (ranks follow each game's ladder)."""

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        assert isinstance(model, AccountTableModel)  # noqa: S101 - wiring invariant
        a = model.sort_key(left.row(), left.column())
        b = model.sort_key(right.row(), right.column())
        return bool(a < b)
