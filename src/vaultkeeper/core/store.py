"""The storage interface services depend on, plus all-or-nothing change application.

``VaultService`` satisfies ``VaultStore``. Tests use a small in-memory fake.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from vaultkeeper.core.models import VaultData


class VaultStore(Protocol):
    """Unlocked vault data plus a way to persist it."""

    @property
    def data(self) -> VaultData: ...

    def save(self) -> None: ...


def apply_change(store: VaultStore, change: Callable[[VaultData], None]) -> None:
    """Apply ``change`` to the vault data and save. If saving fails, roll the change back.

    Models are immutable, so shallow list snapshots are enough to restore the old state.
    The in-memory data therefore never differs from what is on disk.
    """
    data = store.data
    games, accounts, updated_at = list(data.games), list(data.accounts), data.updated_at
    try:
        change(data)
        store.save()
    except BaseException:
        data.games[:] = games
        data.accounts[:] = accounts
        data.updated_at = updated_at
        raise
