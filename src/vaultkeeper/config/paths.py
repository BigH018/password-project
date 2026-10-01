"""Platform-specific locations for settings and logs. Stdlib only.

The vault file itself lives wherever the user chooses at creation time. Its path is stored in
settings and is not derived here.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path

from vaultkeeper.config.constants import APP_DIR_NAME

SETTINGS_FILE_NAME = "settings.json"
LOG_DIR_NAME = "logs"


def app_data_dir(
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return the per-user application data directory (not created).

    Windows: ``%APPDATA%\\VaultKeeper``; macOS: ``~/Library/Application Support/VaultKeeper``;
    others: ``$XDG_CONFIG_HOME/VaultKeeper`` or ``~/.config/VaultKeeper``.
    Arguments exist for testing. They default to the real environment.
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    home = Path.home() if home is None else home

    if platform == "win32":
        base = env.get("APPDATA")
        root = Path(base) if base else home / "AppData" / "Roaming"
    elif platform == "darwin":
        root = home / "Library" / "Application Support"
    else:
        base = env.get("XDG_CONFIG_HOME")
        root = Path(base) if base else home / ".config"
    return root / APP_DIR_NAME


def settings_path(data_dir: Path) -> Path:
    """Return the settings file path inside ``data_dir``."""
    return data_dir / SETTINGS_FILE_NAME


def log_dir(data_dir: Path) -> Path:
    """Return the log directory inside ``data_dir``."""
    return data_dir / LOG_DIR_NAME
