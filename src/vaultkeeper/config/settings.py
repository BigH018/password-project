"""Non-secret user settings, stored as JSON in the app data directory.

Settings never contain account data or secrets: only paths, timeouts and UI preferences.
Loading is forgiving. A missing, corrupt or out-of-range value falls back to its default,
so a broken settings file can never stop the app from starting.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from vaultkeeper.config import constants as c
from vaultkeeper.errors import ValidationError, VaultIOError

log = logging.getLogger(__name__)

SETTINGS_VERSION = 1
MAX_PATH_LENGTH = 4096


@dataclass(frozen=True, slots=True)
class Settings:
    """User-configurable, non-secret settings."""

    vault_path: str | None = None
    backup_dir: str | None = None
    backup_keep: int = c.DEFAULT_BACKUP_KEEP
    backup_min_interval_minutes: int = c.DEFAULT_BACKUP_MIN_INTERVAL_MINUTES
    clipboard_clear_seconds: int = c.DEFAULT_CLIPBOARD_CLEAR_SECONDS
    autolock_minutes: int = c.DEFAULT_AUTOLOCK_MINUTES
    quick_add_autolock_minutes: int = c.DEFAULT_QUICK_ADD_AUTOLOCK_MINUTES
    lock_on_minimize: bool = c.DEFAULT_LOCK_ON_MINIMIZE
    lock_on_session_lock: bool = c.DEFAULT_LOCK_ON_SESSION_LOCK


_INT_RANGES: dict[str, tuple[int, int]] = {
    "backup_keep": c.BACKUP_KEEP_RANGE,
    "backup_min_interval_minutes": c.BACKUP_MIN_INTERVAL_MINUTES_RANGE,
    "clipboard_clear_seconds": c.CLIPBOARD_CLEAR_SECONDS_RANGE,
    "autolock_minutes": c.AUTOLOCK_MINUTES_RANGE,
    "quick_add_autolock_minutes": c.AUTOLOCK_MINUTES_RANGE,
}
_BOOL_FIELDS = frozenset({"lock_on_minimize", "lock_on_session_lock"})
_PATH_FIELDS = frozenset({"vault_path", "backup_dir"})


def _valid_path(value: Any) -> bool:
    return (
        value is None
        or (isinstance(value, str) and 0 < len(value) <= MAX_PATH_LENGTH and "\x00" not in value)
    )


def _valid_value(name: str, value: Any) -> bool:
    if name in _PATH_FIELDS:
        return _valid_path(value)
    if name in _BOOL_FIELDS:
        return isinstance(value, bool)
    if name in _INT_RANGES:
        low, high = _INT_RANGES[name]
        return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high
    return False


def settings_from_dict(raw: Any) -> Settings:
    """Build Settings from a parsed JSON object. Invalid or unknown entries are ignored."""
    if not isinstance(raw, dict):
        return Settings()
    values: dict[str, Any] = {}
    for f in fields(Settings):
        if f.name in raw:
            if _valid_value(f.name, raw[f.name]):
                values[f.name] = raw[f.name]
            else:
                log.warning("Ignoring invalid settings value for %s", f.name)
    return Settings(**values)


def settings_to_dict(settings: Settings) -> dict[str, Any]:
    """Serialize Settings to a JSON-safe dict including the settings version."""
    return {"settings_version": SETTINGS_VERSION, **asdict(settings)}


def validate_settings(settings: Settings) -> Settings:
    """Return ``settings`` unchanged if every value is valid. Otherwise raise ValidationError."""
    for f in fields(Settings):
        if not _valid_value(f.name, getattr(settings, f.name)):
            raise ValidationError(f.name, "invalid value")
    return settings


def load_settings(path: Path) -> Settings:
    """Load settings from ``path``. Returns defaults if the file is missing or unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    except OSError:
        log.warning("Could not read settings file; using defaults")
        return Settings()
    try:
        raw = json.loads(text)
    except ValueError:
        log.warning("Settings file is not valid JSON; using defaults")
        return Settings()
    return settings_from_dict(raw)


def save_settings(path: Path, settings: Settings) -> None:
    """Atomically write settings to ``path`` (tmp file + fsync + replace)."""
    validate_settings(settings)
    data = json.dumps(settings_to_dict(settings), indent=2, sort_keys=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise VaultIOError("Could not save settings.") from exc


def update_settings(settings: Settings, **changes: Any) -> Settings:
    """Return a copy of ``settings`` with ``changes`` applied and validated."""
    return validate_settings(replace(settings, **changes))
