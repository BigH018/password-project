"""Domain dataclasses: Rank, Game, Account, VaultData. No I/O and no validation logic.

Accounts, games and ranks are immutable. Services create updated copies with
``dataclasses.replace``. Secret and PII fields are excluded from ``repr`` so an accidental
log or traceback can't print them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from vaultkeeper.config.constants import DEFAULT_STATUS, GamePreset
from vaultkeeper.core.game_template import GameTemplate

SCHEMA_VERSION = 3

# Fields holding secrets: masked in UI, auto-cleared from clipboard, never logged.
SECRET_FIELDS: tuple[str, ...] = ("password", "email_password", "totp_secret")


def new_id() -> str:
    """Return a new random UUID4 string (uuid4 draws from os.urandom)."""
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with offset, second precision."""
    return datetime.now(UTC).replace(microsecond=0).isoformat()


@dataclass(frozen=True, slots=True)
class Rank:
    """A two-part rank. ``tier=None`` means Unranked (then ``division`` is None too)."""

    tier: str | None = None
    division: int | None = None

    @property
    def is_unranked(self) -> bool:
        """True when no tier is set."""
        return self.tier is None


@dataclass(frozen=True, slots=True)
class Game:
    """A game that groups accounts. Its ``template`` defines ranks, regions and fields."""

    id: str
    name: str
    template: GameTemplate = field(default_factory=GameTemplate)

    @property
    def rank_preset(self) -> GamePreset:
        """The template's ladder/regions in the shape the rank helpers use."""
        return self.template.to_preset()


@dataclass(frozen=True, slots=True)
class Account:
    """One game account. See docs/DATA_MODEL.md for field rules."""

    id: str
    game_id: str
    display_name: str = field(default="", repr=False)
    tag: str | None = field(default=None, repr=False)
    login_username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    email: str = field(default="", repr=False)
    email_password: str | None = field(default=None, repr=False)
    email_login_url: str | None = field(default=None, repr=False)
    region: str | None = None
    rank: Rank = field(default_factory=Rank)
    status: str = DEFAULT_STATUS
    recovery_email: str | None = field(default=None, repr=False)
    totp_secret: str | None = field(default=None, repr=False)
    tags: tuple[str, ...] = field(default=(), repr=False)
    notes: str = field(default="", repr=False)
    # Extra (per-game, user-defined) field values as sorted (field_id, value) pairs.
    extra: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    created_at: str = ""
    updated_at: str = ""

    def __repr__(self) -> str:
        return f"Account(id={self.id!r}, game_id={self.game_id!r})"

    __str__ = __repr__

    def extra_value(self, field_id: str) -> str:
        """Value of an extra field ("" if unset)."""
        return dict(self.extra).get(field_id, "")

    @property
    def riot_id(self) -> str:
        """``name#tag`` when a tag is set, otherwise just the display name."""
        return f"{self.display_name}#{self.tag}" if self.tag else self.display_name


@dataclass(slots=True)
class VaultData:
    """Everything stored inside the encrypted vault payload."""

    games: list[Game] = field(default_factory=list)
    accounts: list[Account] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __repr__(self) -> str:
        return f"VaultData(games={len(self.games)}, accounts={len(self.accounts)})"

    @classmethod
    def empty(cls) -> VaultData:
        """Return a new empty vault with creation timestamps set."""
        now = utc_now_iso()
        return cls(created_at=now, updated_at=now)
