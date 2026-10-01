"""Filtering and rank ordering for the account list. Pure functions, no state.

Free-text search covers identifying and descriptive fields: name, tag, Riot ID, login,
emails, labels, notes, region, status and rank. It NEVER looks at secrets (password, email
password, TOTP secret).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from vaultkeeper.config.constants import GamePreset, format_rank
from vaultkeeper.core.models import Account

# Put this in AccountFilter.tiers to match unranked accounts.
UNRANKED = None


@dataclass(frozen=True, slots=True)
class AccountFilter:
    """Criteria are combined with AND. An empty set or empty text means "any".

    - ``statuses``, ``tiers``, ``regions``: the account's value must be in the set.
      ``tiers`` may contain ``UNRANKED`` (None).
    - ``tags``: the account must have ALL of these labels (case-insensitive).
    - ``text``: every whitespace-separated word must appear somewhere (case-insensitive).
    """

    game_id: str | None = None
    statuses: frozenset[str] = field(default_factory=frozenset)
    tiers: frozenset[str | None] = field(default_factory=frozenset)
    regions: frozenset[str] = field(default_factory=frozenset)
    tags: frozenset[str] = field(default_factory=frozenset)
    text: str = ""

    @property
    def is_empty(self) -> bool:
        """True when the filter matches everything."""
        return not (self.game_id or self.statuses or self.tiers or self.regions or self.tags
                    or self.text.strip())


def searchable_text(account: Account) -> str:
    """Case-folded text that free-text search runs against (never includes secrets)."""
    parts = [
        account.display_name, account.tag or "", account.riot_id, account.login_username,
        account.email, account.recovery_email or "", account.notes, account.region or "",
        account.status, account.rank.tier or "unranked",
        str(account.rank.division) if account.rank.division is not None else "",
        *account.tags,
    ]  # fmt: skip
    return "\n".join(parts).casefold()


def matches(account: Account, flt: AccountFilter) -> bool:
    """Whether ``account`` satisfies every criterion in ``flt``."""
    if flt.game_id is not None and account.game_id != flt.game_id:
        return False
    if flt.statuses and account.status not in flt.statuses:
        return False
    if flt.tiers and account.rank.tier not in flt.tiers:
        return False
    if flt.regions and account.region not in flt.regions:
        return False
    if flt.tags:
        have = {t.casefold() for t in account.tags}
        if not all(t.casefold() in have for t in flt.tags):
            return False
    words = flt.text.casefold().split()
    if words:
        haystack = searchable_text(account)
        if not all(w in haystack for w in words):
            return False
    return True


def filter_accounts(accounts: Iterable[Account], flt: AccountFilter) -> list[Account]:
    """Accounts matching ``flt``, in their original order."""
    return [a for a in accounts if matches(a, flt)]


@dataclass(frozen=True, slots=True)
class Facets:
    """Distinct values present in a set of accounts, for filter dropdowns (sorted)."""

    tiers: tuple[str, ...]
    regions: tuple[str, ...]
    tags: tuple[str, ...]


def facets(accounts: Iterable[Account], preset: GamePreset | None = None) -> Facets:
    """Values to offer in the filter dropdowns.

    With a fixed-ladder ``preset`` (one game selected), tiers and regions come from the
    preset in ladder order. Otherwise they are the distinct values present, sorted. Tags are
    always the labels present (case-insensitively distinct, first spelling kept).
    """
    accounts = list(accounts)
    tags: dict[str, str] = {}
    for account in accounts:
        for tag in account.tags:
            tags.setdefault(tag.casefold(), tag)
    if preset is not None and not preset.free_text:
        tiers, regions = preset.tier_names, preset.regions
    else:
        tiers = tuple(sorted({a.rank.tier for a in accounts if a.rank.tier}, key=str.casefold))
        regions = tuple(sorted({a.region for a in accounts if a.region}, key=str.casefold))
    return Facets(tiers, regions, tuple(sorted(tags.values(), key=str.casefold)))


def rank_sort_key(account: Account, preset: GamePreset) -> tuple[int, int, int, str]:
    """Sort key ordering accounts from lowest to highest rank within a preset's ladder.

    Unranked sorts first. A tier with no division sorts below the same tier with one.
    Tiers not in the ladder (free-text presets, or tiers renamed since) sort after known
    tiers, alphabetically.
    """
    tier = account.rank.tier
    if tier is None:
        return (0, 0, 0, "")
    spec = preset.tier(tier)
    if spec is None:
        return (2, 0, 0, tier.casefold())
    division = account.rank.division
    div_index = spec.divisions.index(division) + 1 if division in spec.divisions else 0
    return (1, preset.tier_names.index(tier), div_index, "")


def rank_label(account: Account, preset: GamePreset) -> str:
    """Display text for the account's rank in its game's style."""
    return format_rank(preset, account.rank.tier, account.rank.division)
