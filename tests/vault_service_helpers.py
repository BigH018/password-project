"""Shared helpers for the vault service tests (not a test module)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fake_data import make_account, make_game
from vaultkeeper.core.vault_service import VaultService

Factory = Callable[..., VaultService]


def populate(service: VaultService) -> None:
    game = make_game()
    service.data.games.append(game)
    service.data.accounts.append(make_account(game))
    service.save()


class DeferredRunner:
    """Captures tasks to prove the prepare step doesn't touch service state."""

    def __init__(self) -> None:
        self.pending: list[tuple[Any, Any, Any]] = []

    def submit(self, task: Any, on_success: Any, on_error: Any) -> None:
        self.pending.append((task, on_success, on_error))

    def run(self) -> None:
        """Run the latest task and deliver its result, like the real runners."""
        task, on_success, on_error = self.pending.pop()
        try:
            result = task()
        except Exception as exc:  # noqa: BLE001 - delivered like the real runners do
            on_error(exc)
            return
        on_success(result)
