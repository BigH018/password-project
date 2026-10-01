"""Non-secret user settings, stored as JSON in the app data directory.

Settings never contain account data or secrets: only paths, timeouts, UI preferences
(including the main window's size/position as an opaque base64 blob) and backup status times.
Loading is forgiving. A missing, corrupt or out-of-range value falls back to its default,
so a broken settings file can never stop the app from starting.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import string
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from vaultkeeper.config import constants as c
from vaultkeeper.errors import ValidationError, VaultIOError

log = logging.getLogger(__name__)

SETTINGS_VERSION = 1
MAX_PATH_LENGTH = 4096
MAX_GEOMETRY_LENGTH = 2048
MAX_TIMESTAMP_LENGTH = 40
_BASE64_CHARS = frozenset(string.ascii_letters + string.digits + "+/=")
_NEW_FILE = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)


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
    show_passwords_seconds: int = c.DEFAULT_SHOW_PASSWORDS_SECONDS
    exclude_from_capture: bool = c.DEFAULT_EXCLUDE_FROM_CAPTURE
    window_geometry: str | None = None  # Qt saveGeometry() as base64; None = default size
    backup_last_success: str | None = None  # UTC ISO-8601 of the last good backup
    backup_last_failure: str | None = None  # set until a backup succeeds again
    # Last vault ``updated_at`` this PC saw, per vault path (timestamps only, SEC-M3).
    vault_last_saved: dict[str, str] = field(default_factory=dict)


_INT_RANGES: dict[str, tuple[int, int]] = {
    "backup_keep": c.BACKUP_KEEP_RANGE,
    "backup_min_interval_minutes": c.BACKUP_MIN_INTERVAL_MINUTES_RANGE,
    "clipboard_clear_seconds": c.CLIPBOARD_CLEAR_SECONDS_RANGE,
    "autolock_minutes": c.AUTOLOCK_MINUTES_RANGE,
    "quick_add_autolock_minutes": c.AUTOLOCK_MINUTES_RANGE,
    "show_passwords_seconds": c.SHOW_PASSWORDS_SECONDS_RANGE,
}
_BOOL_FIELDS = frozenset({"lock_on_minimize", "lock_on_session_lock", "exclude_from_capture"})
_PATH_FIELDS = frozenset({"vault_path", "backup_dir"})
_TIMESTAMP_FIELDS = frozenset({"backup_last_success", "backup_last_failure"})


def _valid_path(value: Any) -> bool:
    return (
        value is None
        or (isinstance(value, str) and 0 < len(value) <= MAX_PATH_LENGTH and "\x00" not in value)
    )


def _valid_geometry(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and 0 < len(value) <= MAX_GEOMETRY_LENGTH
        and set(value) <= _BASE64_CHARS
    )


def _valid_timestamp(value: Any) -> bool:
    """None or a timezone-aware ISO-8601 timestamp."""
    if value is None:
        return True
    if not isinstance(value, str) or not 0 < len(value) <= MAX_TIMESTAMP_LENGTH:
        return False
    try:
        return datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def _valid_last_saved(value: Any) -> bool:
    """{vault path: timezone-aware ISO timestamp}, at most c.MAX_REMEMBERED_VAULTS."""
    return isinstance(value, dict) and len(value) <= c.MAX_REMEMBERED_VAULTS and all(
        isinstance(k, str) and k and _valid_path(k) and v is not None and _valid_timestamp(v)
        for k, v in value.items())


def _valid_value(name: str, value: Any) -> bool:
    if name == "window_geometry":
        return _valid_geometry(value)
    if name in _TIMESTAMP_FIELDS:
        return _valid_timestamp(value)
    if name == "vault_last_saved":
        return _valid_last_saved(value)
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
        tmp.unlink(missing_ok=True)  # a leftover (or planted link) is removed, never followed
        fd = os.open(tmp, _NEW_FILE, 0o600)  # exclusive: never writes through a link
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
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


class SettingsFile:
    """The current settings and the file they live in. ``update`` validates, keeps, saves."""

    def __init__(self, path: Path, settings: Settings) -> None:
        self.path = path
        self.current = settings

    def update(self, **changes: Any) -> bool:
        """Apply ``changes`` (ValidationError if invalid) and save. False if saving failed.

        The new values are kept in memory either way; nothing is written if nothing changed.
        """
        updated = update_settings(self.current, **changes)
        if updated == self.current:
            return True
        self.current = updated
        return self.save()

    def save(self) -> bool:
        """Write the current settings. Failures are logged (no paths) and return False."""
        try:
            save_settings(self.path, self.current)
        except VaultIOError:
            log.warning("Could not save settings")
            return False
        return True
