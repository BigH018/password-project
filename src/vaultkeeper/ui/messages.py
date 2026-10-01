"""User-facing wording for errors, plus small shared dialogs.

Texts stay generic: they never echo passwords, account data or which check failed.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox, QWidget

from vaultkeeper.errors import (
    ValidationError,
    VaultAuthError,
    VaultFormatError,
    VaultIOError,
    VaultKeeperError,
    WeakPasswordError,
)

AUTH_FAILED = "Wrong password or the vault file is damaged."
DAMAGED_FILE = "The vault file is damaged or isn't an Account Manager vault."
UNEXPECTED = "Something went wrong. The details (without any of your data) were logged."


def error_text(exc: BaseException) -> str:
    """Friendly text for an exception raised by a service."""
    if isinstance(exc, VaultAuthError):
        return AUTH_FAILED
    if isinstance(exc, VaultFormatError):
        return DAMAGED_FILE
    if isinstance(exc, WeakPasswordError):
        return f"Master password {exc.reason}."
    if isinstance(exc, ValidationError):
        return f"{exc.field.replace('_', ' ').capitalize()} {exc.reason}."
    if isinstance(exc, VaultIOError | VaultKeeperError):
        return str(exc)
    return UNEXPECTED


def show_error(parent: QWidget | None, title: str, text: str) -> None:
    """Modal error box."""
    QMessageBox.critical(parent, title, text)


def confirm(parent: QWidget | None, title: str, text: str, ok_text: str = "OK") -> bool:
    """Modal yes/no question. Returns True only if the user clicks ``ok_text``."""
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.Cancel, parent)
    ok = box.addButton(ok_text, QMessageBox.AcceptRole)
    box.setDefaultButton(QMessageBox.Cancel)
    box.exec_()
    return box.clickedButton() is ok
