"""Throwaway demo environment with obviously fake accounts (``python -m vaultkeeper --demo``).

Everything lives in a fresh ``vaultkeeper-demo-*`` folder in the system temp directory: the
vault, its settings and its logs. The real settings folder is never touched. The folder is
deleted on exit. Leftovers from a crash are swept away the next time a demo starts.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path

from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.game_template import (
    CustomField,
    FieldKind,
    GameTemplate,
    TierDef,
    starter_template,
)
from vaultkeeper.core.models import Rank, new_id
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.crypto.kdf import DEFAULT_KDF_PARAMS, KdfParams

log = logging.getLogger(__name__)

DEMO_PREFIX = "vaultkeeper-demo-"
# Intentionally public: printed in the terminal, protects fake demo data only.
DEMO_PASSWORD = "demo fake passphrase only"  # noqa: S105

_GAMES = (
    ("Valorant", "valorant", ("EU", "NA", "AP", "KR"),
     (Rank("Iron", 2), Rank("Gold", 3), Rank("Platinum", 2), Rank("Ascendant", 1),
      Rank("Immortal", 3), Rank("Radiant", None), Rank())),
    ("Marvel Rivals", "marvel_rivals", ("EU", "NA", "Asia"),
     (Rank("Bronze", 3), Rank("Gold", 2), Rank("Diamond", 1), Rank("Celestial", 3),
      Rank("Eternity", None), Rank())),
    ("Overwatch", "overwatch", ("Europe", "Americas", "Asia"),
     (Rank("Silver", 5), Rank("Platinum", 3), Rank("Master", 1), Rank("Champion", 4),
      Rank("Top 500", None), Rank())),
    ("Apex Legends", "apex", ("EU", "NA West", "NA East"),
     (Rank("Diamond", 4), Rank("Apex Predator", None), Rank())),
)  # fmt: skip
_COUNTS = {"valorant": 12, "marvel_rivals": 8, "overwatch": 7, "apex": 3}

# A user-built template, the way someone would set up a game with no built-in preset.
_LEGEND = CustomField(new_id(), "Main legend", FieldKind.CHOICE,
                      ("Wraith", "Bloodhound", "Lifeline"))
_LEVEL = CustomField(new_id(), "Account level", FieldKind.NUMBER)
_BACKUP = CustomField(new_id(), "Backup code", FieldKind.SECRET)
_APEX = GameTemplate(
    tiers=(TierDef("Rookie", 4), TierDef("Bronze", 4), TierDef("Silver", 4), TierDef("Gold", 4),
           TierDef("Platinum", 4), TierDef("Diamond", 4), TierDef("Master"),
           TierDef("Apex Predator")),
    best_division_is_one=True,
    roman_divisions=True,
    regions=("EU", "NA West", "NA East", "Asia"),
    hidden_fields=frozenset({"tag"}),
    custom_fields=(_LEGEND, _LEVEL, _BACKUP),
)
_STATUSES = ("active", "active", "active", "banned", "locked", "retired")


@dataclass(frozen=True, slots=True)
class DemoEnv:
    """Paths of one demo run (all inside ``root``)."""

    root: Path
    data_dir: Path
    vault_path: Path


def _seed(service: VaultService) -> None:
    games, accounts = GameService(service), AccountService(service)
    number = 0
    for name, preset, regions, ranks in _GAMES:
        game = games.add(name, _APEX if preset == "apex" else starter_template(preset))
        for i in range(_COUNTS[preset]):
            number += 1
            status = _STATUSES[number % len(_STATUSES)]
            accounts.add(replace(
                accounts.new_draft(game.id),
                display_name=f"DemoAlt{number:02d}",
                tag="DEMO" if i % 3 and preset != "apex" else None,
                login_username=f"demo_login_{number:02d}",
                password=f"Fake-Demo-Pass-{number:02d}",
                email=f"demo{number:02d}@example.test",
                region=regions[i % len(regions)],
                rank=ranks[i % len(ranks)],
                status=status,
                tags=("demo", "main") if i == 0 else ("demo", "smurf"),
                notes="Fake demo account. Banned in a pretend ranked game." if status == "banned"
                else "Fake demo account.",
                extra=_apex_extra(i) if preset == "apex" else (),
            ))


def _apex_extra(i: int) -> tuple[tuple[str, str], ...]:
    values = {_LEGEND.id: _LEGEND.choices[i % 3], _LEVEL.id: str(100 + 50 * i),
              _BACKUP.id: f"FAKE-CODE-{i:04d}"}
    return tuple(sorted(values.items()))


def sweep_stale_demo_dirs(base: Path | None = None) -> None:
    """Delete leftover demo folders (from a crash) in the temp directory."""
    root = Path(base or tempfile.gettempdir())
    for leftover in root.glob(f"{DEMO_PREFIX}*"):
        if leftover.is_dir():
            shutil.rmtree(leftover, ignore_errors=True)


def create_demo_env(
    base: Path | None = None, kdf_params: KdfParams = DEFAULT_KDF_PARAMS
) -> DemoEnv:
    """Create a fresh temp folder holding a demo vault full of fake accounts."""
    root = Path(tempfile.mkdtemp(prefix=DEMO_PREFIX, dir=base))
    env = DemoEnv(root=root, data_dir=root / "appdata", vault_path=root / "demo.vault")
    service = VaultService(env.vault_path, kdf_params=kdf_params)
    service.create(DEMO_PASSWORD)
    try:
        _seed(service)
    finally:
        service.lock()
    log.info("Demo vault created in a temporary folder")
    return env


def cleanup_demo_env(env: DemoEnv) -> bool:
    """Delete the demo folder. Returns True if it is gone.

    Refuses anything that isn't a demo folder. Close log handlers first: on Windows an open
    log file stops the folder from being deleted.
    """
    if not env.root.name.startswith(DEMO_PREFIX):
        raise ValueError("refusing to delete a folder that is not a demo folder")
    for _attempt in range(2):
        shutil.rmtree(env.root, ignore_errors=True)
        if not env.root.exists():
            return True
        time.sleep(0.2)  # give Windows a moment to release file handles
    log.warning("Demo folder could not be fully deleted; it will be removed on the next demo")
    return False
