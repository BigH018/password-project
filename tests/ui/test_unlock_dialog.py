"""Unlock dialog: success, wrong password, no freeze, closable while busy, explicit backup."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QDialog

from conftest import FAST_KDF, MASTER
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.storage import vault_file
from vaultkeeper.ui.messages import AUTH_FAILED
from vaultkeeper.ui.qt_adapters import QtTaskRunner
from vaultkeeper.ui.unlock_dialog import UnlockDialog

Factory = Callable[..., VaultService]


def _dialog(qtbot: Any, service: VaultService, runner: QtTaskRunner) -> UnlockDialog:
    dialog = UnlockDialog(service, runner.cancel_pending)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def _submit(dialog: UnlockDialog, password: str, *, backup: bool = False) -> None:
    dialog.password.setText(password)
    (dialog.backup_button if backup else dialog.unlock_button).click()


def test_correct_password_unlocks(qtbot: Any, existing_vault: Path, make_qt_service: Factory,
                                  qt_runner: QtTaskRunner) -> None:
    service = make_qt_service()
    dialog = _dialog(qtbot, service, qt_runner)
    _submit(dialog, MASTER)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.Accepted, timeout=5000)
    assert service.is_unlocked and not service.opened_from_backup


def test_wrong_password_generic_message(qtbot: Any, make_qt_service: Factory,
                                        qt_runner: QtTaskRunner, vault_path: Path) -> None:
    VaultService(vault_path, kdf_params=FAST_KDF).create(MASTER)  # no .bak
    service = make_qt_service()
    dialog = _dialog(qtbot, service, qt_runner)
    _submit(dialog, "wrong fake passphrase")
    qtbot.waitUntil(lambda: bool(dialog.error_label.text()), timeout=5000)
    assert dialog.error_label.text() == AUTH_FAILED
    assert dialog.password.text() == ""
    assert dialog.isVisible() and not service.is_unlocked
    assert dialog.backup_button.isHidden()  # no .bak exists


def test_empty_password_does_nothing(qtbot: Any, existing_vault: Path, make_qt_service: Factory,
                                     qt_runner: QtTaskRunner) -> None:
    dialog = _dialog(qtbot, make_qt_service(), qt_runner)
    dialog.unlock_button.click()
    assert "Enter your master password" in dialog.error_label.text()
    assert not dialog.busy


def test_ui_stays_responsive_while_kdf_runs(qtbot: Any, existing_vault: Path, gate: Any,
                                            make_qt_service: Factory,
                                            qt_runner: QtTaskRunner) -> None:
    service = make_qt_service(kdf=gate.kdf)
    dialog = _dialog(qtbot, service, qt_runner)
    _submit(dialog, MASTER)
    assert dialog.busy and dialog.busy_bar.isVisible()
    assert not dialog.unlock_button.isEnabled() and not dialog.password.isEnabled()
    assert dialog.quit_button.isEnabled()  # can always walk away

    ticked: list[bool] = []
    QTimer.singleShot(50, lambda: ticked.append(True))
    qtbot.waitUntil(lambda: bool(ticked), timeout=2000)  # event loop not frozen
    assert dialog.busy

    gate.release()
    qtbot.waitUntil(lambda: dialog.result() == QDialog.Accepted, timeout=5000)
    assert not dialog.busy_bar.isVisible()


def test_closing_while_busy_discards_result(qtbot: Any, existing_vault: Path, gate: Any,
                                            make_qt_service: Factory,
                                            qt_runner: QtTaskRunner) -> None:
    service = make_qt_service(kdf=gate.kdf)
    dialog = _dialog(qtbot, service, qt_runner)
    _submit(dialog, MASTER)
    assert gate.entered.wait(5)
    dialog.close()  # window close button: never blocked
    assert not dialog.isVisible() and dialog.result() == QDialog.Rejected
    gate.release()
    qtbot.wait(400)
    assert not service.is_unlocked  # late result was thrown away


@pytest.fixture
def damaged_with_bak(existing_vault: Path) -> bytes:
    raw = bytearray(existing_vault.read_bytes())
    raw[-1] ^= 0x01
    existing_vault.write_bytes(bytes(raw))
    return bytes(raw)


def test_never_opens_backup_silently(qtbot: Any, existing_vault: Path, damaged_with_bak: bytes,
                                     make_qt_service: Factory, qt_runner: QtTaskRunner,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_qt_service()
    calls: list[bool] = []
    real_unlock = service.unlock_async

    def spy_unlock(password: str, on_done: Any, on_error: Any, *, use_backup: bool = False) -> None:
        calls.append(use_backup)
        real_unlock(password, on_done, on_error, use_backup=use_backup)

    monkeypatch.setattr(service, "unlock_async", spy_unlock)
    reads: list[Path] = []
    real_read = vault_file.read_vault_bytes
    monkeypatch.setattr(vault_file, "read_vault_bytes",
                        lambda p: reads.append(p) or real_read(p))

    dialog = _dialog(qtbot, service, qt_runner)
    assert dialog.backup_button.isHidden()
    _submit(dialog, MASTER)  # the CORRECT password, but the main file is damaged
    qtbot.waitUntil(lambda: bool(dialog.error_label.text()), timeout=5000)

    assert dialog.result() != QDialog.Accepted and dialog.isVisible()
    assert not service.is_unlocked
    assert calls == [False]
    assert service.backup_path not in reads  # the .bak was never even read
    assert existing_vault.read_bytes() == damaged_with_bak  # nothing swapped or rewritten
    assert dialog.backup_button.isVisible() and dialog.backup_note.isVisible()
    assert "sure your password is right" in dialog.backup_note.text()

    _submit(dialog, MASTER, backup=True)  # explicit user choice
    qtbot.waitUntil(lambda: dialog.result() == QDialog.Accepted, timeout=5000)
    assert calls == [False, True]
    assert service.is_unlocked and service.opened_from_backup


def test_backup_button_needs_password(qtbot: Any, existing_vault: Path, damaged_with_bak: bytes,
                                      make_qt_service: Factory, qt_runner: QtTaskRunner) -> None:
    dialog = _dialog(qtbot, make_qt_service(), qt_runner)
    _submit(dialog, MASTER)
    qtbot.waitUntil(lambda: dialog.backup_button.isVisible(), timeout=5000)
    dialog.backup_button.click()  # field was cleared after the failed attempt
    assert "Enter your master password" in dialog.error_label.text()
    assert not dialog.busy


def test_no_backup_offer_without_bak(qtbot: Any, vault_path: Path, make_qt_service: Factory,
                                     qt_runner: QtTaskRunner) -> None:
    vault_path.write_bytes(b"definitely not a vault" * 4)
    assert not vault_file.backup_path(vault_path).exists()
    dialog = _dialog(qtbot, make_qt_service(), qt_runner)
    _submit(dialog, MASTER)
    qtbot.waitUntil(lambda: bool(dialog.error_label.text()), timeout=5000)
    assert "damaged" in dialog.error_label.text()
    assert dialog.backup_button.isHidden()


def test_other_vault_file_link(qtbot: Any, existing_vault: Path, make_qt_service: Factory,
                               qt_runner: QtTaskRunner, tmp_path: Path) -> None:
    picks = ["", str(tmp_path / "restored.vault")]
    dialog = UnlockDialog(make_qt_service(), qt_runner.cancel_pending,
                          choose_file=lambda _p: picks.pop(0))
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.other_button.isFlat()  # low-key link, not a main button
    dialog.other_button.click()  # picker cancelled
    assert dialog.isVisible() and dialog.other_vault_path is None
    dialog.other_button.click()
    assert dialog.other_vault_path == tmp_path / "restored.vault"
    assert dialog.result() == QDialog.Rejected


def test_low_memory_shows_a_friendly_message(qtbot: Any, existing_vault: Path,
                                             make_qt_service: Factory,
                                             qt_runner: QtTaskRunner,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-Low4: Argon2 failing (e.g. low memory) isn't "wrong password" or a crash notice."""
    from argon2.exceptions import HashingError

    from vaultkeeper.crypto import kdf

    def low_memory(**_kw: object) -> bytes:
        raise HashingError("Memory allocation error")

    monkeypatch.setattr(kdf, "hash_secret_raw", low_memory)
    dialog = _dialog(qtbot, make_qt_service(kdf=kdf.derive_key), qt_runner)
    _submit(dialog, MASTER)
    qtbot.waitUntil(lambda: bool(dialog.error_label.text()), timeout=5000)
    assert "memory" in dialog.error_label.text() and dialog.error_label.text() != AUTH_FAILED
    assert dialog.isVisible()
