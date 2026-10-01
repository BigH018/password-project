"""Account CRUD and duplicate detection.

Every change is validated against the account's game preset, saved immediately, and rolled
back in memory if the save fails (see ``core/store.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from vaultkeeper.config.constants import get_preset
from vaultkeeper.core.models import Account, Game, VaultData, new_id, utc_now_iso
from vaultkeeper.core.store import VaultStore, apply_change
from vaultkeeper.core.validation import validate_account
from vaultkeeper.errors import NotFoundError, ValidationError

log = logging.getLogger(__name__)


class DuplicateField(StrEnum):
    """Which identifier matched an existing account."""

    LOGIN = "login_username"
    RIOT_ID = "riot_id"


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    """An existing account that looks like the candidate. A warning only, never a block."""

    account_id: str
    field: DuplicateField


def _norm(value: Any) -> str:
    return value.strip().casefold() if isinstance(value, str) else ""


def _riot_key(account: Account) -> str | None:
    name = _norm(account.display_name)
    if not name:
        return None
    return f"{name}#{_norm(account.tag)}"


class AccountService:
    """Create, read, update and delete accounts in the unlocked vault."""

    def __init__(self, store: VaultStore, clock: Callable[[], str] = utc_now_iso) -> None:
        self._store = store
        self._clock = clock

    @property
    def _data(self) -> VaultData:
        return self._store.data

    # --- reads ------------------------------------------------------------------------------

    def get(self, account_id: str) -> Account:
        """Return the account or raise NotFoundError."""
        for account in self._data.accounts:
            if account.id == account_id:
                return account
        raise NotFoundError("Account not found.")

    def list_all(self) -> list[Account]:
        """All accounts (unsorted; sorting is a view concern)."""
        return list(self._data.accounts)

    def list_for_game(self, game_id: str) -> list[Account]:
        """Accounts belonging to one game."""
        return [a for a in self._data.accounts if a.game_id == game_id]

    def _game(self, game_id: str) -> Game:
        for game in self._data.games:
            if game.id == game_id:
                return game
        raise ValidationError("game_id", "is not an existing game")

    # --- writes -----------------------------------------------------------------------------

    def new_draft(self, game_id: str) -> Account:
        """A blank account for ``game_id`` with a fresh id, for forms to fill in."""
        self._game(game_id)
        return Account(id=new_id(), game_id=game_id)

    def add(self, draft: Account) -> Account:
        """Validate and store a new account. Sets both timestamps."""
        if any(a.id == draft.id for a in self._data.accounts):
            raise ValidationError("id", "already exists")
        game = self._game(draft.game_id)
        now = self._clock()
        account = validate_account(replace(draft, created_at=now, updated_at=now),
                                   get_preset(game.preset))
        apply_change(self._store, lambda data: data.accounts.append(account))
        log.info("Account added id=%s game=%s", account.id, account.game_id)
        return account

    def update(self, edited: Account) -> Account:
        """Validate and replace an existing account. Moving it to another game re-validates
        it against that game's preset. ``created_at`` is preserved."""
        existing = self.get(edited.id)
        game = self._game(edited.game_id)
        account = validate_account(
            replace(edited, created_at=existing.created_at, updated_at=self._clock()),
            get_preset(game.preset),
        )

        def change(data: VaultData) -> None:
            data.accounts[:] = [account if a.id == account.id else a for a in data.accounts]

        apply_change(self._store, change)
        log.info("Account updated id=%s", account.id)
        return account

    def delete(self, account_id: str) -> None:
        """Remove an account (the UI asks for confirmation first)."""
        self.get(account_id)

        def change(data: VaultData) -> None:
            data.accounts[:] = [a for a in data.accounts if a.id != account_id]

        apply_change(self._store, change)
        log.info("Account deleted id=%s", account_id)

    # --- duplicates -------------------------------------------------------------------------

    def find_duplicates(self, candidate: Account) -> list[DuplicateMatch]:
        """Accounts in the same game with the same login, or the same name#tag.

        Comparison trims and ignores case. ``candidate`` may be an unvalidated draft (checked
        while typing). The candidate's own id is skipped, so editing doesn't flag itself.
        """
        login = _norm(candidate.login_username)
        riot = _riot_key(candidate)
        matches: list[DuplicateMatch] = []
        for other in self._data.accounts:
            if other.id == candidate.id or other.game_id != candidate.game_id:
                continue
            if login and _norm(other.login_username) == login:
                matches.append(DuplicateMatch(other.id, DuplicateField.LOGIN))
            elif riot and _riot_key(other) == riot:
                matches.append(DuplicateMatch(other.id, DuplicateField.RIOT_ID))
        return matches
