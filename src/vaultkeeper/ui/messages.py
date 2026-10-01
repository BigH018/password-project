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
from vaultkeeper.ui.safe_text import message_box

AUTH_FAILED = "Wrong password or the vault file is damaged."
DAMAGED_FILE = "The vault file is damaged or isn't an Account Manager vault."
UNEXPECTED = "Something went wrong. The details (without any of your data) were logged."

# Service field names -> the labels the user sees on screen.
FIELD_LABELS = {
    "account": "The account",
    "character_types": "Character types",
    "display_name": "Name",
    "email": "Email",
    "email_login_url": "Email login URL",
    "email_password": "Email password",
    "export_file": "Export file",
    "extra_fields": "Extra fields",
    "fields": "Shown fields",
    "game_id": "Game",
    "game_name": "Game name",
    "id": "Internal ID",
    "length": "Password length",
    "login_username": "Login",
    "master_password": "Master password",
    "notes": "Notes",
    "password": "Password",
    "preset": "Game preset",
    "rank": "Rank",
    "ranks": "Ranks",
    "recovery_email": "Recovery email",
    "region": "Region",
    "regions": "Regions",
    "status": "Status",
    "tag": "Tag",
    "tags": "Labels",
    "totp_secret": "2FA key",
}
# Reasons starting with one of these read as "<Label> <reason>"; others as "<Label>: <reason>".
_VERB_STARTS = ("is ", "must ", "has ", "needs ", "contains ", "can't ", "already ")


def field_label(field: str) -> str:
    """On-screen label for a field (extra fields already use the user's own label)."""
    if field in FIELD_LABELS:
        return FIELD_LABELS[field]
    text = field.replace("_", " ")
    return text[:1].upper() + text[1:]


def validation_text(field: str, reason: str) -> str:
    """One readable sentence for a ValidationError (never includes the value)."""
    joiner = " " if reason.startswith(_VERB_STARTS) else ": "
    return f"{field_label(field)}{joiner}{reason}."


def error_text(exc: BaseException) -> str:
    """Friendly text for an exception raised by a service."""
    if isinstance(exc, VaultAuthError):
        return AUTH_FAILED
    if isinstance(exc, VaultFormatError):
        return DAMAGED_FILE
    if isinstance(exc, WeakPasswordError):
        return f"Master password {exc.reason}."
    if isinstance(exc, ValidationError):
        return validation_text(exc.field, exc.reason)
    if isinstance(exc, VaultIOError | VaultKeeperError):
        return str(exc)
    return UNEXPECTED


def show_error(parent: QWidget | None, title: str, text: str) -> None:
    """Modal error box (plain text: ``text`` may name the user's data)."""
    box = message_box(QMessageBox.Critical, title, text, QMessageBox.Ok, parent)
    box.exec_()


def confirm(parent: QWidget | None, title: str, text: str, ok_text: str = "OK") -> bool:
    """Modal yes/no question. Returns True only if the user clicks ``ok_text``."""
    box = message_box(QMessageBox.Question, title, text, QMessageBox.Cancel, parent)
    ok = box.addButton(ok_text, QMessageBox.AcceptRole)
    box.setDefaultButton(QMessageBox.Cancel)
    box.exec_()
    return box.clickedButton() is ok
