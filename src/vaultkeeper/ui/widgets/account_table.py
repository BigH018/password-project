"""Account table: model with masked passwords, plus a proxy that sorts with proper keys."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from vaultkeeper.config.constants import GamePreset
from vaultkeeper.core.game_template import CustomField, FieldKind
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
        self._presets: dict[str, GamePreset] = {}  # built once per set_rows, not per cell
        self._columns = COLUMNS
        self._extra_fields: dict[str, CustomField] = {}
        self._show_passwords = False

    # --- data in ------------------------------------------------------------------------

    def set_rows(self, accounts: list[Account], games: dict[str, Game], show_game: bool,
                 single_game: Game | None = None) -> None:
        """Replace all rows. ``games`` maps game id to Game (names and templates).

        With ``single_game`` (one game selected), columns follow its template: Rank/Region
        columns hide if the game hides those fields, and non-secret extra fields get columns.
        """
        self.beginResetModel()
        self._rows = list(accounts)
        self._games = dict(games)
        self._presets = {game_id: game.rank_preset for game_id, game in self._games.items()}
        columns = [c for c in COLUMNS if show_game or c[0] != "game"]
        if single_game is not None:
            template = single_game.template
            columns = [c for c in columns
                       if c[0] not in ("rank", "region") or template.shows(c[0])]
            extras = [f for f in template.custom_fields if f.kind is not FieldKind.SECRET]
            insert_at = [c[0] for c in columns].index("tags")
            columns[insert_at:insert_at] = [(f"x:{f.id}", f.label) for f in extras]
            self._extra_fields = {f.id: f for f in extras}
        else:
            self._extra_fields = {}
        self._columns = tuple(columns)
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
        if key.startswith("x:"):
            field_id = key[2:]
            # Secret extra fields never get a column; this is a second guard.
            if field_id not in self._extra_fields:
                return ""
            return account.extra_value(field_id)
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
            preset = self._presets.get(account.game_id)
            return rank_label(account, preset) if preset else ""
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
            preset = self._presets.get(account.game_id)
            return rank_sort_key(account, preset) if preset else (2, 0, 0, "")
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
