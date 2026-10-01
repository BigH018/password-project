"""Game management: add, rename, change preset, delete (blocked while accounts exist)."""

from __future__ import annotations

import logging
from dataclasses import replace

from vaultkeeper.config.constants import DEFAULT_PRESET_KEY, get_preset
from vaultkeeper.core.models import Game, VaultData, new_id
from vaultkeeper.core.store import VaultStore, apply_change
from vaultkeeper.core.validation import clean_game_name, clean_preset_key, validate_account
from vaultkeeper.errors import (
    DuplicateGameError,
    GameInUseError,
    NotFoundError,
    ValidationError,
)

log = logging.getLogger(__name__)


def _plural(n: int) -> str:
    return f"{n} account" if n == 1 else f"{n} accounts"


class GameService:
    """CRUD for games. Every change is saved immediately (and rolled back if saving fails)."""

    def __init__(self, store: VaultStore) -> None:
        self._store = store

    @property
    def _data(self) -> VaultData:
        return self._store.data

    def list_games(self) -> list[Game]:
        """All games, sorted by name (case-insensitive)."""
        return sorted(self._data.games, key=lambda g: g.name.casefold())

    def get(self, game_id: str) -> Game:
        """Return the game or raise NotFoundError."""
        for game in self._data.games:
            if game.id == game_id:
                return game
        raise NotFoundError("Game not found.")

    def account_counts(self) -> dict[str, int]:
        """Number of accounts per game id (games without accounts map to 0)."""
        counts = {g.id: 0 for g in self._data.games}
        for account in self._data.accounts:
            counts[account.game_id] = counts.get(account.game_id, 0) + 1
        return counts

    def _ensure_unique(self, name: str, exclude_id: str | None = None) -> None:
        key = name.casefold()
        for game in self._data.games:
            if game.id != exclude_id and game.name.casefold() == key:
                raise DuplicateGameError("A game with this name already exists.")

    def _replace(self, updated: Game) -> None:
        def change(data: VaultData) -> None:
            data.games[:] = [updated if g.id == updated.id else g for g in data.games]

        apply_change(self._store, change)

    def add(self, name: str, preset: str = DEFAULT_PRESET_KEY) -> Game:
        """Create a game. Names are unique, ignoring case."""
        game = Game(id=new_id(), name=clean_game_name(name), preset=clean_preset_key(preset))
        self._ensure_unique(game.name)
        apply_change(self._store, lambda data: data.games.append(game))
        log.info("Game added id=%s", game.id)
        return game

    def rename(self, game_id: str, name: str) -> Game:
        """Rename a game. Accounts reference the id, so nothing else changes."""
        game = self.get(game_id)
        cleaned = clean_game_name(name)
        self._ensure_unique(cleaned, exclude_id=game_id)
        updated = replace(game, name=cleaned)
        self._replace(updated)
        log.info("Game renamed id=%s", game_id)
        return updated

    def set_preset(self, game_id: str, preset: str) -> Game:
        """Change a game's preset, but only if every account still validates under it."""
        game = self.get(game_id)
        new_preset = get_preset(clean_preset_key(preset))
        failures = 0
        for account in self._data.accounts:
            if account.game_id == game_id:
                try:
                    validate_account(account, new_preset)
                except ValidationError:
                    failures += 1
        if failures:
            raise ValidationError(
                "preset",
                f"{_plural(failures)} would become invalid with this preset "
                "(rank or region not in its lists); edit them first",
            )
        updated = replace(game, preset=new_preset.key)
        self._replace(updated)
        log.info("Game preset changed id=%s", game_id)
        return updated

    def delete(self, game_id: str) -> None:
        """Delete a game. Blocked while any account belongs to it."""
        self.get(game_id)
        in_use = self.account_counts().get(game_id, 0)
        if in_use:
            raise GameInUseError(
                f"This game still has {_plural(in_use)}. Move or delete them first."
            )

        def change(data: VaultData) -> None:
            data.games[:] = [g for g in data.games if g.id != game_id]

        apply_change(self._store, change)
        log.info("Game deleted id=%s", game_id)
