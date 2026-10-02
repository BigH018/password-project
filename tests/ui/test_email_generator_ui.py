"""Email generator UI: dialog, account form button, Tools menu, domain setting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtWidgets import QDialog, QWidget

from conftest import FAST_KDF
from test_clipboard import FakeClipboard
from vaultkeeper import demo
from vaultkeeper.config.settings import Settings
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.security.clipboard import ClipboardGuard
from vaultkeeper.ui import main_window as mw
from vaultkeeper.ui.email_generator_dialog import EmailGeneratorDialog
from vaultkeeper.ui.settings_dialog import SettingsDialog
from vaultkeeper.ui.widgets.account_form import AccountForm

DOMAIN = "example.test"


@pytest.fixture
def unlocked(tmp_path: Path) -> VaultService:
    env = demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock(demo.DEMO_PASSWORD)
    return svc


def _dialog(qtbot: Any, taken: frozenset[str] = frozenset(), **kwargs: Any
            ) -> EmailGeneratorDialog:
    dialog = EmailGeneratorDialog(DOMAIN, lambda: taken, **kwargs)
    qtbot.addWidget(dialog)
    return dialog


# --- dialog -----------------------------------------------------------------------------------


def test_dialog_generates_copies_and_uses(qtbot: Any) -> None:
    copied: list[str] = []
    dialog = _dialog(qtbot, game_name="Marvel Rivals", copy=copied.append, allow_use=True)
    first = dialog.preview.text()
    assert re.fullmatch(r"marvelrivals\.[a-z2-9]{4}@example\.test", first)
    dialog.regenerate_button.click()
    dialog.length.setValue(10)
    assert re.fullmatch(r"marvelrivals\.[a-z2-9]{10}@example\.test", dialog.preview.text())
    dialog.copy_button.click()
    assert copied == [dialog.preview.text()]
    chosen = dialog.preview.text()
    dialog.use_button.click()
    assert dialog.result() == QDialog.Accepted and dialog.email == chosen


def test_dialog_asks_for_the_game_name(qtbot: Any) -> None:
    dialog = _dialog(qtbot)
    assert dialog.preview.text().startswith("acct.")
    dialog.game_name.setText("Overwatch 2")
    assert dialog.preview.text().startswith("overwatch2.")
    assert dialog.copy_button.isHidden() and dialog.use_button.isHidden()


def test_dialog_skips_addresses_in_the_vault(qtbot: Any, monkeypatch: pytest.MonkeyPatch
                                             ) -> None:
    from vaultkeeper.core import email_generator as eg

    draws = iter(["aaaa", "bbbb"])
    monkeypatch.setattr(eg, "random_part", lambda _length: next(draws))
    dialog = _dialog(qtbot, taken=frozenset({"valorant.aaaa@example.test"}),
                     game_name="Valorant")
    assert dialog.preview.text() == "valorant.bbbb@example.test"


def test_dialog_bad_domain_shows_error(qtbot: Any) -> None:
    dialog = EmailGeneratorDialog("not a domain", frozenset, allow_use=True)
    qtbot.addWidget(dialog)
    assert dialog.preview.text() == "" and not dialog.use_button.isEnabled()
    assert dialog.error_label.text().startswith("Email domain is not a valid domain")


# --- account form ------------------------------------------------------------------------------


def test_form_generate_email_fills_email(qtbot: Any, unlocked: VaultService) -> None:
    asked: list[str] = []

    def pick(game_name: str, _parent: QWidget) -> str:
        asked.append(game_name)
        return "valorant.k7q4@example.test"

    form = AccountForm(list(unlocked.data.games), pick_email=pick)
    qtbot.addWidget(form)
    form.load(AccountService(unlocked).new_draft(unlocked.data.games[0].id))
    form.generate_email_button.click()
    assert asked == [unlocked.data.games[0].name]
    assert form.email.text() == "valorant.k7q4@example.test"


def test_form_closed_generator_keeps_email(qtbot: Any, unlocked: VaultService) -> None:
    form = AccountForm(list(unlocked.data.games), pick_email=lambda _name, _parent: "")
    qtbot.addWidget(form)
    form.email.setText("player1@example.test")
    form.generate_email_button.click()
    assert form.email.text() == "player1@example.test"


def test_form_without_generator_hides_button(qtbot: Any, unlocked: VaultService) -> None:
    form = AccountForm(list(unlocked.data.games))
    qtbot.addWidget(form)
    assert form.generate_email_button.isHidden()


# --- main window ---------------------------------------------------------------------------------


def test_tools_menu_action_and_vault_addresses(qtbot: Any, unlocked: VaultService) -> None:
    window = mw.MainWindow()
    qtbot.addWidget(window)
    tools_menu = window.menuBar().actions()[2].menu()
    assert window.email_generator_action in tools_menu.actions()
    assert window.email_generator_action.shortcut().toString() == "Ctrl+Shift+G"
    assert not window.email_generator_action.isEnabled()  # locked: no vault to check
    assert window._addresses_in_use() == frozenset()
    accounts = AccountService(unlocked)
    window.show_unlocked(str(unlocked.path), False, accounts, GameService(unlocked))
    assert window.email_generator_action.isEnabled()
    assert window._addresses_in_use() == accounts.addresses_in_use() != frozenset()


def test_launcher_copies_as_email(qtbot: Any, unlocked: VaultService) -> None:
    board = FakeClipboard()
    window = mw.MainWindow()
    qtbot.addWidget(window)
    window.copy.clipboard = ClipboardGuard(board, lambda _s, _fn: None, clear_after=15)
    window.email_tools._copy("valorant.k7q4@example.test")
    assert board.value == "valorant.k7q4@example.test"
    assert window.statusBar().currentMessage().startswith("Email copied")


# --- settings ------------------------------------------------------------------------------------


def test_settings_dialog_domain(qtbot: Any) -> None:
    dialog = SettingsDialog(Settings(email_domain="mail.example.test"))
    qtbot.addWidget(dialog)
    assert dialog.values()["email_domain"] == "mail.example.test"
    dialog.domain_edit.setText("  @Example.TEST ")
    assert dialog.values()["email_domain"] == "example.test"
    dialog.restore_defaults()
    assert dialog.values()["email_domain"] == "example.com"


def test_settings_dialog_refuses_bad_domain(qtbot: Any) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.domain_edit.setText("not a domain")
    dialog.save_button.click()
    assert dialog.isVisible() and "Email generator domain" in dialog.error_label.text()
    dialog.domain_edit.setText("example.test")
    assert dialog.error_label.text() == ""
    dialog.save_button.click()
    assert dialog.result() == QDialog.Accepted
