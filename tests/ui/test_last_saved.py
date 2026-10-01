"""SEC-M3: "Last saved" after unlock, and a warning if the vault went back in time."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import FAST_KDF, MASTER
from vaultkeeper.config.settings import Settings
from vaultkeeper.core.vault_disk import vault_key
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui import app_controller, messages
from vaultkeeper.ui.qt_adapters import QtTaskRunner

FUTURE = "2099-01-01T00:00:00+00:00"  # "this PC saw a newer version"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    path = tmp_path / "fake.vault"
    svc = VaultService(path, kdf_params=FAST_KDF)
    svc.create(MASTER)
    svc.save()  # so a .bak exists too
    return path


@pytest.fixture
def warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(messages, "show_warning", lambda _p, _t, text: seen.append(text))
    return seen


def _controller(qtbot: Any, tmp_path: Path, vault: Path, monkeypatch: pytest.MonkeyPatch,
                seen: dict[str, str] | None = None, use_backup: bool = False) -> Any:
    class FakeUnlock:
        def __init__(self, service: VaultService, *_a: Any, **_k: Any) -> None:
            self.service, self.other_vault_path = service, None

        def deleteLater(self) -> None:  # noqa: N802 - Qt API (run_modal)
            pass

        def exec_(self) -> int:
            self.service.unlock(MASTER, use_backup=use_backup)
            return 1

    monkeypatch.setattr(app_controller, "UnlockDialog", FakeUnlock)
    settings = Settings(vault_path=str(vault), vault_last_saved=seen or {})
    controller = app_controller.AppController(
        settings, tmp_path / "s.json", QtTaskRunner(),
        lambda p: VaultService(p, kdf_params=FAST_KDF))
    qtbot.addWidget(controller.window)
    controller.start()
    return controller


def test_unlock_shows_last_saved_and_remembers_it(qtbot: Any, tmp_path: Path, vault: Path,
                                                  warnings: list[str],
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _controller(qtbot, tmp_path, vault, monkeypatch)
    updated = controller.service.data.updated_at
    assert "Last saved: " in controller.window.statusBar().currentMessage()
    assert controller.settings.current.vault_last_saved == {vault_key(vault): updated}
    assert warnings == []


def test_saving_updates_the_remembered_time(qtbot: Any, tmp_path: Path, vault: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _controller(qtbot, tmp_path, vault, monkeypatch)
    controller.service.data.updated_at = "2000-01-01T00:00:00+00:00"
    controller.service.save()  # sets a fresh updated_at
    remembered = controller.settings.current.vault_last_saved[vault_key(vault)]
    assert remembered == controller.service.data.updated_at != "2000-01-01T00:00:00+00:00"


def test_older_vault_warns_once(qtbot: Any, tmp_path: Path, vault: Path, warnings: list[str],
                                monkeypatch: pytest.MonkeyPatch) -> None:
    controller = _controller(qtbot, tmp_path, vault, monkeypatch,
                             seen={vault_key(vault): FUTURE})
    assert len(warnings) == 1 and "old copy" in warnings[0]
    assert controller.service.is_unlocked  # a warning, not a block
    # The user has been told: this file is the reference from now on.
    assert controller.settings.current.vault_last_saved[vault_key(vault)] != FUTURE
    controller.lock()
    qtbot.waitUntil(lambda: controller.service.is_unlocked, timeout=5000)
    assert len(warnings) == 1


def test_opening_the_backup_copy_never_warns(qtbot: Any, tmp_path: Path, vault: Path,
                                             warnings: list[str],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    _controller(qtbot, tmp_path, vault, monkeypatch, seen={vault_key(vault): FUTURE},
                use_backup=True)
    assert warnings == []


# --- CR-L7: say where the damaged copy was kept --------------------------------------------


def test_damaged_copy_location_is_reported_once(qtbot: Any, tmp_path: Path, vault: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    shown: list[str] = []
    monkeypatch.setattr(messages, "show_warning", lambda _p, _t, text: shown.append(text))
    damaged = bytearray(vault.read_bytes())
    damaged[-1] ^= 0x01
    vault.write_bytes(bytes(damaged))
    controller = _controller(qtbot, tmp_path, vault, monkeypatch, use_backup=True)
    assert shown == []
    controller.service.save()  # the damaged main file is copied aside now
    kept = controller.service.last_damaged_copy
    assert kept is not None and kept.exists()
    assert len(shown) == 1 and str(kept) in shown[0]
    controller.service.save()
    assert len(shown) == 1  # reported once
