"""Create vault dialog: validation messages, strength hint, success, close while busy."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt5.QtWidgets import QDialog

from conftest import MASTER
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui.create_vault_dialog import CreateVaultDialog
from vaultkeeper.ui.qt_adapters import QtTaskRunner

Factory = Callable[..., VaultService]


def _dialog(qtbot: Any, factory: Factory, runner: QtTaskRunner, path: Path,
            **service_options: Any) -> CreateVaultDialog:
    dialog = CreateVaultDialog(lambda p: factory(path=p, **service_options),
                               runner.cancel_pending, path)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def _fill(dialog: CreateVaultDialog, password: str, confirm: str | None = None) -> None:
    dialog.password.setText(password)
    dialog.confirm.setText(password if confirm is None else confirm)
    dialog.create_button.click()


def test_creates_vault(qtbot: Any, make_qt_service: Factory, qt_runner: QtTaskRunner,
                       tmp_path: Path) -> None:
    target = tmp_path / "sub" / "new.vault"
    dialog = _dialog(qtbot, make_qt_service, qt_runner, target)
    _fill(dialog, MASTER)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.Accepted, timeout=5000)
    assert target.exists()
    assert dialog.service is not None and dialog.service.is_unlocked
    assert dialog.password.text() == "" and dialog.confirm.text() == ""


def test_adds_vault_extension(qtbot: Any, make_qt_service: Factory, qt_runner: QtTaskRunner,
                              tmp_path: Path) -> None:
    dialog = _dialog(qtbot, make_qt_service, qt_runner, tmp_path / "myvault")
    _fill(dialog, MASTER)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.Accepted, timeout=5000)
    assert (tmp_path / "myvault.vault").exists()


def test_weak_and_mismatched_passwords_blocked(qtbot: Any, make_qt_service: Factory,
                                               qt_runner: QtTaskRunner, tmp_path: Path) -> None:
    target = tmp_path / "x.vault"
    dialog = _dialog(qtbot, make_qt_service, qt_runner, target)
    _fill(dialog, "short")
    assert "at least 12" in dialog.error_label.text()
    _fill(dialog, MASTER, "something else entirely")
    assert "don't match" in dialog.error_label.text()
    assert not dialog.busy and not target.exists()


def test_existing_file_refused(qtbot: Any, make_qt_service: Factory, qt_runner: QtTaskRunner,
                               tmp_path: Path) -> None:
    target = tmp_path / "taken.vault"
    target.write_bytes(b"existing")
    dialog = _dialog(qtbot, make_qt_service, qt_runner, target)
    _fill(dialog, MASTER)
    assert "already exists" in dialog.error_label.text()
    assert target.read_bytes() == b"existing"


def test_strength_meter_updates(qtbot: Any, make_qt_service: Factory, qt_runner: QtTaskRunner,
                                tmp_path: Path) -> None:
    dialog = _dialog(qtbot, make_qt_service, qt_runner, tmp_path / "x.vault")
    assert dialog.meter.label.text() == "Strength: -"
    dialog.password.setText("abc")
    weak = dialog.meter.bar.value()
    dialog.password.setText("lamp orbit cactus tide river")
    assert dialog.meter.bar.value() > weak
    assert "abc" not in dialog.meter.label.text() + dialog.meter.suggestions.text()


def test_closing_while_creating_writes_nothing(qtbot: Any, make_qt_service: Factory,
                                               qt_runner: QtTaskRunner, tmp_path: Path,
                                               gate: Any) -> None:
    target = tmp_path / "abandoned.vault"
    dialog = _dialog(qtbot, make_qt_service, qt_runner, target, kdf=gate.kdf)
    _fill(dialog, MASTER)
    assert dialog.busy and gate.entered.wait(5)
    assert dialog.cancel_button.isEnabled()
    dialog.close()
    assert dialog.result() == QDialog.Rejected and dialog.service is None
    gate.release()
    qtbot.wait(400)
    assert not target.exists()
