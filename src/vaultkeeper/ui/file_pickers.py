"""File and folder pickers built from Qt's own dialog, never the native Windows one (CR-L5).

A native picker runs its own message loop: clicks and typing in it never reach Qt's app-wide
activity filter (auto-lock could trip while you browse), and it isn't a QDialog, so locking
can't close it. Qt's dialog is an ordinary QDialog: activity counts, and lock closes it like
every other dialog. Each returns the chosen path, or "" if cancelled.
"""

from __future__ import annotations

from PyQt5.QtWidgets import QFileDialog, QWidget

from vaultkeeper.config.constants import VAULT_EXTENSION
from vaultkeeper.ui.messages import run_modal

VAULT_FILTER = f"Vault files (*{VAULT_EXTENSION})"


def _picker(parent: QWidget | None, title: str, start: str, mode: QFileDialog.FileMode,
            accept: QFileDialog.AcceptMode = QFileDialog.AcceptOpen) -> QFileDialog:
    dialog = QFileDialog(parent, title, start)
    dialog.setOption(QFileDialog.DontUseNativeDialog, True)
    dialog.setFileMode(mode)
    dialog.setAcceptMode(accept)
    return dialog


def _run(dialog: QFileDialog) -> str:
    if not run_modal(dialog):
        return ""
    files = dialog.selectedFiles()
    return files[0] if files else ""


def choose_folder(parent: QWidget | None, title: str, start: str) -> str:
    """Pick an existing folder."""
    dialog = _picker(parent, title, start, QFileDialog.Directory)
    dialog.setOption(QFileDialog.ShowDirsOnly, True)
    return _run(dialog)


def choose_save_file(parent: QWidget | None, title: str, start: str) -> str:
    """Pick where to save a .vault file (asks before replacing an existing one)."""
    dialog = _picker(parent, title, start, QFileDialog.AnyFile, QFileDialog.AcceptSave)
    dialog.setNameFilter(VAULT_FILTER)
    dialog.setDefaultSuffix(VAULT_EXTENSION.lstrip("."))
    return _run(dialog)


def choose_open_file(parent: QWidget | None, title: str, start: str) -> str:
    """Pick an existing .vault file."""
    dialog = _picker(parent, title, start, QFileDialog.ExistingFile)
    dialog.setNameFilter(VAULT_FILTER)
    return _run(dialog)
