"""SecretField.clear() wipes Qt's undo history, so a cleared password can't come back (SEC-H2).

Qt hides undo in password mode, but after "Show" switches to normal echo mode, an undo
after QLineEdit.clear() would restore the cleared text.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from conftest import FAST_KDF, MASTER
from vaultkeeper.core.tasks import InlineTaskRunner
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui.change_password_dialog import ChangePasswordDialog
from vaultkeeper.ui.create_vault_dialog import CreateVaultDialog
from vaultkeeper.ui.export_dialog import ExportDialog
from vaultkeeper.ui.qt_adapters import QtTaskRunner
from vaultkeeper.ui.unlock_dialog import UnlockDialog
from vaultkeeper.ui.widgets.secret_field import SecretField

TYPED = "Fake-Passw0rd-1!"
Factory = Callable[..., VaultService]


def _type_into_all(qtbot: Any, widget: Any) -> list[SecretField]:
    fields = widget.findChildren(SecretField)
    assert fields
    for field in fields:
        qtbot.keyClicks(field.edit, TYPED)
        assert field.text() == TYPED
    return fields


def _stays_empty_after_undo(field: SecretField) -> None:
    assert field.text() == ""
    field.toggle.click()  # Show: normal echo mode re-enables undo
    assert field.revealed
    field.edit.undo()
    assert field.text() == "", "undo restored a cleared secret"
    assert not field.edit.isUndoAvailable()
    field.toggle.click()


def test_clear_wipes_undo_history(qtbot: Any) -> None:
    field = SecretField()
    qtbot.addWidget(field)
    qtbot.keyClicks(field.edit, TYPED)
    field.toggle.click()
    field.clear()
    assert not field.revealed  # clear() masks it again
    _stays_empty_after_undo(field)


def test_unlock_dialog_clear(qtbot: Any, make_qt_service: Factory, qt_runner: QtTaskRunner,
                             existing_vault: Path) -> None:
    dialog = UnlockDialog(make_qt_service(), qt_runner.cancel_pending)
    qtbot.addWidget(dialog)
    fields = _type_into_all(qtbot, dialog)
    dialog.reject()
    for field in fields:
        _stays_empty_after_undo(field)


def test_change_password_dialog_clear(qtbot: Any, make_qt_service: Factory,
                                      qt_runner: QtTaskRunner) -> None:
    service = make_qt_service()
    service.create(MASTER)
    dialog = ChangePasswordDialog(service, qt_runner.cancel_pending)
    qtbot.addWidget(dialog)
    fields = _type_into_all(qtbot, dialog)
    dialog._clear_fields()
    for field in fields:
        _stays_empty_after_undo(field)


def test_create_vault_dialog_clear(qtbot: Any, make_qt_service: Factory,
                                   qt_runner: QtTaskRunner, tmp_path: Path) -> None:
    dialog = CreateVaultDialog(lambda p: make_qt_service(path=p), qt_runner.cancel_pending,
                               tmp_path / "new.vault")
    qtbot.addWidget(dialog)
    fields = _type_into_all(qtbot, dialog)
    dialog.reject()
    for field in fields:
        _stays_empty_after_undo(field)


def test_export_dialog_clear(qtbot: Any, tmp_path: Path) -> None:
    service = VaultService(tmp_path / "fake.vault", kdf_params=FAST_KDF)
    service.create(MASTER)
    dialog = ExportDialog(b"{}", service.path, InlineTaskRunner(), lambda: None,
                          tmp_path / "export.vault", writer=lambda *_a, **_k: True)
    qtbot.addWidget(dialog)
    fields = _type_into_all(qtbot, dialog)
    dialog._clear()
    for field in fields:
        _stays_empty_after_undo(field)
