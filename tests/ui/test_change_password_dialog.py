"""Change master password dialog: checks, success, wrong current, closable while busy."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PyQt5.QtWidgets import QDialog

from conftest import FAST_KDF, MASTER, OTHER_MASTER
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui.change_password_dialog import ChangePasswordDialog
from vaultkeeper.ui.messages import AUTH_FAILED
from vaultkeeper.ui.qt_adapters import QtTaskRunner

Factory = Callable[..., VaultService]


def _open(qtbot: Any, factory: Factory, runner: QtTaskRunner,
          **options: Any) -> tuple[VaultService, ChangePasswordDialog]:
    service = factory(**options)
    service.unlock(MASTER) if service.exists() else service.create(MASTER)
    dialog = ChangePasswordDialog(service, runner.cancel_pending)
    qtbot.addWidget(dialog)
    dialog.show()
    return service, dialog


def _fill(dialog: ChangePasswordDialog, current: str, new: str, confirm: str | None = None
          ) -> None:
    dialog.current.setText(current)
    dialog.new.setText(new)
    dialog.confirm.setText(new if confirm is None else confirm)
    dialog.change_button.click()


def _opens_with(path: Path, password: str) -> bool:
    try:
        VaultService(path, kdf_params=FAST_KDF).unlock(password)
    except Exception:  # noqa: BLE001 - any failure means "doesn't open"
        return False
    return True


def test_change_succeeds(qtbot: Any, make_qt_service: Factory, qt_runner: QtTaskRunner,
                         vault_path: Path) -> None:
    _service, dialog = _open(qtbot, make_qt_service, qt_runner)
    _fill(dialog, MASTER, OTHER_MASTER)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.Accepted, timeout=5000)
    assert all(not f.text() for f in (dialog.current, dialog.new, dialog.confirm))
    assert _opens_with(vault_path, OTHER_MASTER) and not _opens_with(vault_path, MASTER)


def test_local_checks(qtbot: Any, make_qt_service: Factory, qt_runner: QtTaskRunner) -> None:
    _service, dialog = _open(qtbot, make_qt_service, qt_runner)
    _fill(dialog, "", OTHER_MASTER)
    assert "current master password" in dialog.error_label.text()
    _fill(dialog, MASTER, OTHER_MASTER, "not the same")
    assert "don't match" in dialog.error_label.text()
    _fill(dialog, MASTER, MASTER)
    assert "different" in dialog.error_label.text()
    _fill(dialog, MASTER, "short")
    assert "at least 12" in dialog.error_label.text()
    assert not dialog.busy


def test_wrong_current_password(qtbot: Any, make_qt_service: Factory, qt_runner: QtTaskRunner,
                                vault_path: Path) -> None:
    _service, dialog = _open(qtbot, make_qt_service, qt_runner)
    _fill(dialog, "wrong fake passphrase", OTHER_MASTER)
    qtbot.waitUntil(lambda: bool(dialog.error_label.text()), timeout=5000)
    assert dialog.error_label.text() == AUTH_FAILED
    assert dialog.current.text() == "" and dialog.isVisible()
    assert _opens_with(vault_path, MASTER)


def test_closing_while_busy_keeps_old_password(qtbot: Any, make_qt_service: Factory,
                                               qt_runner: QtTaskRunner, vault_path: Path,
                                               gate: Any) -> None:
    _service, dialog = _open(qtbot, make_qt_service, qt_runner)
    dialog._service._kdf = gate.kdf  # slow down only the change, not the setup
    _fill(dialog, MASTER, OTHER_MASTER)
    assert dialog.busy and gate.entered.wait(5)
    dialog.close()
    assert dialog.result() == QDialog.Rejected
    gate.release()
    qtbot.wait(400)
    assert _opens_with(vault_path, MASTER) and not _opens_with(vault_path, OTHER_MASTER)
