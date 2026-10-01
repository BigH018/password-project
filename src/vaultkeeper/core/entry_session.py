"""Quick Add batch state: sticky game/region/status between entries, plus a session counter.

Pure state, no I/O. Lives while the vault is unlocked (reset on lock).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from vaultkeeper.config.constants import DEFAULT_STATUS
from vaultkeeper.core.models import Account


@dataclass
class EntrySession:
    """What Quick Add remembers between entries."""

    game_id: str | None = None
    region: str | None = None
    status: str = DEFAULT_STATUS
    added: int = 0

    def remember(self, saved: Account) -> None:
        """A save happened: count it and keep its game, region and status for the next one."""
        self.game_id = saved.game_id
        self.region = saved.region
        self.status = saved.status
        self.added += 1

    def starting_game_id(self, selected: str | None) -> str | None:
        """The game Quick Add opens on: the game selected in the sidebar if there is one,
        otherwise the game of the last batch (None: the user picks)."""
        return selected or self.game_id

    def next_draft(self, blank: Account) -> Account:
        """Fill a blank draft (fresh id, chosen game) with the sticky values.

        Region only carries over within the same game (another game has other regions).
        """
        same_game = blank.game_id == self.game_id
        return replace(blank, region=self.region if same_game else None, status=self.status)

    def counter_text(self) -> str:
        """e.g. "43 added this session"."""
        return f"{self.added} added this session"
