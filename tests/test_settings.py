"""Settings load/save, defaults, corrupt-file handling, and paths."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vaultkeeper.config import constants as c
from vaultkeeper.config import paths
from vaultkeeper.config.settings import (
    MAX_GEOMETRY_LENGTH,
    Settings,
    SettingsFile,
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


# --- window geometry (8c) --------------------------------------------------------------------

GEOMETRY = "AdnQywADAAAAAAB4AAAAWgAABK8AAALp"  # opaque base64, as Qt's saveGeometry gives


def test_window_geometry_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(path, Settings(window_geometry=GEOMETRY))
    assert load_settings(path).window_geometry == GEOMETRY


def test_old_settings_file_without_geometry_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"settings_version": 1, "autolock_minutes": 7}))
    loaded = load_settings(path)
    assert loaded.autolock_minutes == 7 and loaded.window_geometry is None


@pytest.mark.parametrize("bad", [
    "", "not base64!", "abc" + chr(0), "<script>", 42, ["x"], "A" * (MAX_GEOMETRY_LENGTH + 1),
])
def test_invalid_geometry_is_ignored(bad: object) -> None:
    assert settings_from_dict({"window_geometry": bad}).window_geometry is None
    with pytest.raises(ValidationError):
        update_settings(Settings(), window_geometry=bad)


# --- SettingsFile ----------------------------------------------------------------------------


def test_settings_file_update_saves(tmp_path: Path) -> None:
    store = SettingsFile(tmp_path / "settings.json", Settings())
    assert store.update(autolock_minutes=9) is True
    assert store.current.autolock_minutes == 9
    assert load_settings(store.path).autolock_minutes == 9


def test_settings_file_skips_write_when_unchanged(tmp_path: Path) -> None:
    store = SettingsFile(tmp_path / "settings.json", Settings())
    assert store.update(autolock_minutes=Settings().autolock_minutes) is True
    assert not store.path.exists()


def test_settings_file_failed_save_keeps_values(tmp_path: Path) -> None:
    blocker = tmp_path / "file-not-folder"
    blocker.write_text("x")
    store = SettingsFile(blocker / "settings.json", Settings())
    assert store.update(autolock_minutes=9) is False
    assert store.current.autolock_minutes == 9


def test_settings_file_rejects_invalid(tmp_path: Path) -> None:
    store = SettingsFile(tmp_path / "settings.json", Settings())
    with pytest.raises(ValidationError):
        store.update(autolock_minutes=0)
    assert store.current == Settings() and not store.path.exists()



# --- backup status (CR-H2) ------------------------------------------------------------------
STAMP = "2026-10-01T12:30:00+00:00"


def test_backup_status_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(path, Settings(backup_last_success=STAMP, backup_last_failure=STAMP))
    loaded = load_settings(path)
    assert loaded.backup_last_success == STAMP and loaded.backup_last_failure == STAMP


@pytest.mark.parametrize("bad", ["yesterday", "2026-10-01T12:30:00", "x" * 100, 5, ""])
def test_invalid_backup_status_is_ignored(bad: object) -> None:
    assert settings_from_dict({"backup_last_failure": bad}).backup_last_failure is None
    with pytest.raises(ValidationError):
        update_settings(Settings(), backup_last_success=bad)
