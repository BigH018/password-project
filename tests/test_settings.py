"""Settings load/save, defaults, corrupt-file handling, and paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vaultkeeper.config import constants as c
from vaultkeeper.config import paths
from vaultkeeper.config.settings import (
    Settings,
    load_settings,
    save_settings,
    settings_from_dict,
    update_settings,
)
from vaultkeeper.errors import ValidationError


def test_defaults_match_approved_decisions() -> None:
    s = Settings()
    assert s.clipboard_clear_seconds == 15
    assert s.autolock_minutes == 5
    assert s.quick_add_autolock_minutes == 15
    assert s.lock_on_minimize and s.lock_on_session_lock
    assert s.backup_keep == 10 and s.backup_min_interval_minutes == 10
    assert s.vault_path is None and s.backup_dir is None


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "nope.json") == Settings()


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "settings.json"
    original = Settings(vault_path=str(tmp_path / "x.vault"), autolock_minutes=10,
                        lock_on_minimize=False)
    save_settings(path, original)
    assert load_settings(path) == original
    assert json.loads(path.read_text(encoding="utf-8"))["settings_version"] == 1
    assert not path.with_name("settings.json.tmp").exists()


@pytest.mark.parametrize("content", ["{not json", "[]", "", "null"])
def test_corrupt_file_gives_defaults(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content, encoding="utf-8")
    assert load_settings(path) == Settings()


def test_invalid_values_fall_back_individually() -> None:
    s = settings_from_dict({
        "autolock_minutes": 0,          # below range
        "clipboard_clear_seconds": 30,  # valid
        "lock_on_minimize": "yes",      # wrong type
        "backup_keep": True,            # bool is not an int here
        "vault_path": "",               # empty path
        "unknown_key": 1,
    })
    assert s.autolock_minutes == c.DEFAULT_AUTOLOCK_MINUTES
    assert s.clipboard_clear_seconds == 30
    assert s.lock_on_minimize is True
    assert s.backup_keep == c.DEFAULT_BACKUP_KEEP
    assert s.vault_path is None


def test_update_settings_validates() -> None:
    assert update_settings(Settings(), autolock_minutes=30).autolock_minutes == 30
    with pytest.raises(ValidationError):
        update_settings(Settings(), clipboard_clear_seconds=1)


def test_save_rejects_invalid(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        save_settings(tmp_path / "s.json", Settings(backup_keep=0))


def test_app_data_dir_per_platform(tmp_path: Path) -> None:
    home = tmp_path
    assert paths.app_data_dir({"APPDATA": "C:/Roaming"}, "win32", home) == \
        Path("C:/Roaming") / "VaultKeeper"
    assert paths.app_data_dir({}, "win32", home) == home / "AppData" / "Roaming" / "VaultKeeper"
    assert paths.app_data_dir({}, "darwin", home) == \
        home / "Library" / "Application Support" / "VaultKeeper"
    assert paths.app_data_dir({"XDG_CONFIG_HOME": "/xdg"}, "linux", home) == \
        Path("/xdg") / "VaultKeeper"
    assert paths.app_data_dir({}, "linux", home) == home / ".config" / "VaultKeeper"


def test_settings_and_log_paths(tmp_path: Path) -> None:
    assert paths.settings_path(tmp_path) == tmp_path / "settings.json"
    assert paths.log_dir(tmp_path) == tmp_path / "logs"
