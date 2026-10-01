"""Account dialog: add, edit, validation errors, duplicate warning, unsaved-changes protection."""

from __future__ import annotations

from typing import Any

import pytest
from PyQt5.QtWidgets import QDialog

from conftest import FakeStore
from fake_data import make_game
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.models import Game, Rank
from vaultkeeper.ui import account_dialog as ad
from vaultkeeper.ui.widgets.secret_field import SecretField


@pytest.fixture
def games(store: FakeStore) -> list[Game]:
    val, ow = make_game("Valorant", "valorant"), make_game("Overwatch", "overwatch")
    store.data.games.extend([val, ow])
    return [val, ow]


@pytest.fixture
def accounts(store: FakeStore) -> AccountService:
    return AccountService(store)


def _open(qtbot: Any, accounts: AccountService, games: list[Game], **kw: Any) -> ad.AccountDialog:
    dialog = ad.AccountDialog(accounts, games, **kw)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def _fill_basic(dialog: ad.AccountDialog, login: str = "fake_login_x") -> None:
    form = dialog.form
    if not form.has_game:
        form.game.setCurrentIndex(1)  # first real game after the placeholder
    form.display_name.setText("FakeAlt")
    form.tag.setText("TEST")
    form.login.setText(login)
    form.password.setText("Fake-Passw0rd-9!")
    form.email.setText("alt@example.test")


def test_add_account(qtbot: Any, accounts: AccountService, games: list[Game],
                     store: FakeStore) -> None:
    dialog = _open(qtbot, accounts, games, default_game_id=games[0].id)
    _fill_basic(dialog)
    dialog.form.region.set_region("EU")
    dialog.form.rank.set_rank(Rank("Ascendant", 2))
    dialog.form.tags.setText("main,  smurf , ")
    dialog.save_button.click()
    assert dialog.result() == QDialog.Accepted
    saved = accounts.get(dialog.saved.id)  # type: ignore[union-attr]
    assert (saved.display_name, saved.tag, saved.region) == ("FakeAlt", "TEST", "EU")
    assert saved.rank == Rank("Ascendant", 2) and saved.tags == ("main", "smurf")
    assert store.saves == 1


def test_secrets_masked_by_default(qtbot: Any, accounts: AccountService,
                                   games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games)
    for field in (dialog.form.password, dialog.form.email_password):
        assert isinstance(field, SecretField) and not field.revealed


def test_validation_error_keeps_dialog_open(qtbot: Any, accounts: AccountService,
                                            games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games)
    _fill_basic(dialog)
    dialog.form.email.setText("not-an-email")
    dialog.save_button.click()
    assert dialog.isVisible() and dialog.result() != QDialog.Accepted
    assert "Email is not a valid email address" in dialog.error_label.text()
    assert "not-an-email" not in dialog.error_label.text()
    assert accounts.list_all() == []


def test_duplicate_warning_does_not_block(qtbot: Any, accounts: AccountService,
                                          games: list[Game]) -> None:
    first = _open(qtbot, accounts, games)
    _fill_basic(first, login="shared_login")
    first.save_button.click()

    second = _open(qtbot, accounts, games)
    second.form.game.setCurrentIndex(second.form.game.findData(games[0].id))
    assert second.duplicate_label.text() == ""
    second.form.login.setText("SHARED_LOGIN")
    assert "same login" in second.duplicate_label.text()
    assert "You can still save" in second.duplicate_label.text()
    second.form.display_name.setText("Other")
    second.save_button.click()
    assert second.result() == QDialog.Accepted and len(accounts.list_all()) == 2


def test_edit_account_and_move_game(qtbot: Any, accounts: AccountService,
                                    games: list[Game]) -> None:
    add = _open(qtbot, accounts, games)
    _fill_basic(add)
    add.save_button.click()
    original = add.saved
    assert original is not None

    edit = _open(qtbot, accounts, games, account=original)
    assert edit.windowTitle() == "Edit account"
    assert edit.form.login.text() == "fake_login_x" and not edit.has_changes
    assert edit.duplicate_label.text() == ""  # editing doesn't flag itself
    edit.form.game.setCurrentIndex(edit.form.game.findData(games[1].id))
    edit.form.region.set_region("Europe")
    edit.form.rank.set_rank(Rank("Master", 4))
    edit.form.status.setCurrentIndex(edit.form.status.findData("banned"))
    edit.save_button.click()
    moved = accounts.get(original.id)
    assert moved.game_id == games[1].id and moved.status == "banned"
    assert moved.created_at == original.created_at


def test_unsaved_changes_prompt(qtbot: Any, accounts: AccountService, games: list[Game],
                                monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    answer = {"discard": False}
    monkeypatch.setattr(ad.messages, "confirm",
                        lambda _p, title, *_a, **_k: asked.append(title) or answer["discard"])

    clean = _open(qtbot, accounts, games)
    clean.cancel_button.click()
    assert asked == [] and clean.result() == QDialog.Rejected  # nothing typed: no prompt

    dirty = _open(qtbot, accounts, games)
    dirty.form.login.setText("half typed")
    dirty.cancel_button.click()
    assert asked == ["Discard changes?"] and dirty.isVisible()  # kept open
    dirty.close()  # window close button routes to the same check
    assert dirty.isVisible() and len(asked) == 2
    answer["discard"] = True
    dirty.reject()
    assert not dirty.isVisible() and accounts.list_all() == []


def test_force_close_never_prompts(qtbot: Any, accounts: AccountService, games: list[Game],
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ad.messages, "confirm", lambda *_a, **_k: pytest.fail("prompted"))
    dialog = _open(qtbot, accounts, games)
    dialog.form.login.setText("draft that will be discarded on lock")
    dialog.force_close()
    assert not dialog.isVisible()


def test_game_change_switches_pickers(qtbot: Any, accounts: AccountService,
                                      games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games, default_game_id=games[0].id)
    assert dialog.form.region.combo.findData("EU") > 0
    dialog.form.game.setCurrentIndex(dialog.form.game.findData(games[1].id))
    assert dialog.form.region.combo.findData("Europe") > 0
    assert dialog.form.rank.tier.findData("Champion") > 0


def test_no_silent_default_game_from_all_games_view(qtbot: Any, accounts: AccountService,
                                                    games: list[Game]) -> None:
    """Regression: with "All games" selected, Add used to pick the first game silently."""
    dialog = _open(qtbot, accounts, games)  # no default_game_id
    assert dialog.form.game.currentText() == "Choose a game..."
    assert not dialog.form.rank.isEnabled() and not dialog.form.region.isEnabled()
    dialog.form.login.setText("fake_login_x")  # fill by hand: _fill_basic would pick a game
    dialog.form.display_name.setText("FakeAlt")
    dialog.save_button.click()
    assert dialog.error_label.text() == "Choose a game first."
    assert accounts.list_all() == []

    dialog.form.game.setCurrentIndex(dialog.form.game.findData(games[1].id))
    assert dialog.form.rank.isEnabled()
    assert dialog.form.rank.tier.findData("Champion") > 0  # a dropdown, not free text
    dialog.save_button.click()
    assert dialog.result() == QDialog.Accepted
    assert accounts.list_all()[0].game_id == games[1].id


def test_game_preselected_when_viewing_a_game(qtbot: Any, accounts: AccountService,
                                              games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games, default_game_id=games[1].id)
    assert dialog.form.game.currentData() == games[1].id
    assert dialog.form.game.findData(None) == -1  # no placeholder needed
