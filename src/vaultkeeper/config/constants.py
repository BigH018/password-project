"""Application-wide constants: statuses, per-game presets, defaults and input limits.

Stdlib only. No other vaultkeeper imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

APP_NAME = "VaultKeeper"  # internal name (package, logs); the user sees DISPLAY_NAME
DISPLAY_NAME = "Account Manager"
WINDOW_TITLE = f"{DISPLAY_NAME} - By BigH"
APP_USER_MODEL_ID = "BigH.AccountManager"  # Windows taskbar grouping + icon
APP_DIR_NAME = "VaultKeeper"
VAULT_EXTENSION = ".vault"


# --- Account status -------------------------------------------------------------------------


class Status(StrEnum):
    """Lifecycle status of an account."""

    ACTIVE = "active"
    BANNED = "banned"
    LOCKED = "locked"
    RETIRED = "retired"


STATUSES: tuple[str, ...] = tuple(s.value for s in Status)
DEFAULT_STATUS = Status.ACTIVE.value


# --- Game presets (rank ladders + regions) ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class TierSpec:
    """One rank tier.

    ``divisions`` is ordered from LOWEST to HIGHEST within the tier. Empty means the tier has
    no divisions (e.g. Radiant).
    """

    name: str
    divisions: tuple[int, ...] = ()

    @property
    def has_divisions(self) -> bool:
        """Whether this tier uses divisions."""
        return bool(self.divisions)


@dataclass(frozen=True, slots=True)
class GamePreset:
    """Rank ladder (lowest tier first), region list and division display style for a game."""

    key: str
    label: str
    tiers: tuple[TierSpec, ...]
    regions: tuple[str, ...]
    roman_divisions: bool = False
    free_text: bool = False  # no fixed ladder/regions: rank and region are typed freely

    def tier(self, name: str) -> TierSpec | None:
        """Return the tier with this exact name, or None."""
        for spec in self.tiers:
            if spec.name == name:
                return spec
        return None

    @property
    def tier_names(self) -> tuple[str, ...]:
        """Tier names, lowest first."""
        return tuple(spec.name for spec in self.tiers)


def _tiers(names: tuple[str, ...], divisions: tuple[int, ...]) -> tuple[TierSpec, ...]:
    return tuple(TierSpec(name, divisions) for name in names)


# Valorant. Source: valorantranks.com / rankforge.gg "Valorant Rank System Explained 2026",
# checked 2026-10-01. Iron..Immortal have divisions 1-3 (3 highest); Radiant has none.
VALORANT = GamePreset(
    key="valorant",
    label="Valorant",
    tiers=_tiers(
        ("Iron", "Bronze", "Silver", "Gold", "Platinum", "Diamond", "Ascendant", "Immortal"),
        (1, 2, 3),
    )
    + (TierSpec("Radiant"),),
    regions=("NA", "EU", "AP", "KR", "LATAM", "BR"),
)

# Marvel Rivals. Source: esports.gg "Marvel Rivals ranks explained", elevateboost.fr
# "Rank System Explained (2026)", checked 2026-10-01. Bronze..Celestial have divisions III-I
# (I highest); Eternity and One Above All have none.
# Regions: UNVERIFIED. No official NetEase list found. Broad groups agreed by third-party
# sources (pingaim.com server map; turbosmurfs.gg "All Marvel Rivals Servers Locations",
# Feb 2025), checked 2026-10-01. Some list 10 city-level servers, grouped here.
MARVEL_RIVALS = GamePreset(
    key="marvel_rivals",
    label="Marvel Rivals",
    tiers=_tiers(
        ("Bronze", "Silver", "Gold", "Platinum", "Diamond", "Grandmaster", "Celestial"),
        (3, 2, 1),
    )
    + (TierSpec("Eternity"), TierSpec("One Above All")),
    regions=("NA", "EU", "Asia", "SA", "OCE", "ME"),
    roman_divisions=True,
)

# Overwatch. Source: Blizzard patch notes (Season 9 competitive update, overwatch.blizzard.com
# 2024/02, which mention divisions within Champion) and dotesports "All Overwatch ranks in
# order", checked 2026-10-01. Bronze..Champion have divisions 5-1 (1 highest). Top 500 is a
# leaderboard placement with no divisions. Some third-party guides claim Champion has no
# divisions; Blizzard's notes take precedence.
OVERWATCH = GamePreset(
    key="overwatch",
    label="Overwatch",
    tiers=_tiers(
        ("Bronze", "Silver", "Gold", "Platinum", "Diamond", "Master", "Grandmaster", "Champion"),
        (5, 4, 3, 2, 1),
    )
    + (TierSpec("Top 500"),),
    regions=("Americas", "Europe", "Asia"),
)

# Any other game: no fixed ladder. Rank (as text, no division) and region are typed freely.
CUSTOM = GamePreset(key="custom", label="Custom", tiers=(), regions=(), free_text=True)

PRESETS: dict[str, GamePreset] = {p.key: p for p in (VALORANT, MARVEL_RIVALS, OVERWATCH, CUSTOM)}
DEFAULT_PRESET_KEY = CUSTOM.key

_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX",
          10: "X"}
UNRANKED_LABEL = "Unranked"


def get_preset(key: str) -> GamePreset:
    """Return the preset for ``key``, falling back to the custom preset for unknown keys."""
    return PRESETS.get(key, CUSTOM)


def format_division(preset: GamePreset, division: int) -> str:
    """Render a division number in the preset's style (e.g. ``2`` or ``II``)."""
    if preset.roman_divisions:
        return _ROMAN.get(division, str(division))
    return str(division)


def format_rank(preset: GamePreset, tier: str | None, division: int | None) -> str:
    """Render a rank such as ``Platinum 2``, ``Gold II`` or ``Unranked``."""
    if tier is None:
        return UNRANKED_LABEL
    if division is None:
        return tier
    return f"{tier} {format_division(preset, division)}"


# --- Input limits (characters) ----------------------------------------------------------------

MAX_GAME_NAME = 64
MAX_DISPLAY_NAME = 64
MAX_TAG = 16  # Riot tag / BattleTag number (part after '#')
MAX_LOGIN = 254
MAX_SECRET = 1024
MAX_EMAIL = 254
MAX_URL = 2048
MAX_REGION = 32
MAX_TIER = 32
MAX_LABEL = 32  # one free-form tag/label
MAX_LABELS = 32  # labels per account
MAX_NOTES = 10_000
MIN_TOTP_SECRET = 16
MAX_TOTP_SECRET = 128


# --- Security / behaviour defaults --------------------------------------------------------------

MASTER_PASSWORD_MIN_LENGTH = 12

DEFAULT_CLIPBOARD_CLEAR_SECONDS = 15
DEFAULT_AUTOLOCK_MINUTES = 5
DEFAULT_QUICK_ADD_AUTOLOCK_MINUTES = 15
DEFAULT_LOCK_ON_MINIMIZE = True
DEFAULT_LOCK_ON_SESSION_LOCK = True
DEFAULT_BACKUP_KEEP = 10
DEFAULT_BACKUP_MIN_INTERVAL_MINUTES = 10

# Allowed ranges for user-configurable settings (inclusive).
CLIPBOARD_CLEAR_SECONDS_RANGE = (5, 300)
AUTOLOCK_MINUTES_RANGE = (1, 240)
BACKUP_KEEP_RANGE = (1, 100)
BACKUP_MIN_INTERVAL_MINUTES_RANGE = (0, 1440)
