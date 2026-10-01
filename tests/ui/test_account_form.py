"""Account form behaviour that isn't about one dialog: name#tag splitting (CR-M3)."""

from __future__ import annotations

from typing import Any

from fake_data import make_account, make_game
from vaultkeeper.ui.widgets.account_form import AccountForm


def _form(qtbot: Any) -> AccountForm:
    game = make_game()
    form = AccountForm([game])
    qtbot.addWidget(form)
    form.load(make_account(game, display_name="", tag=None))
    return form


def test_name_with_tag_is_split_on_focus_out(qtbot: Any) -> None:
    form = _form(qtbot)
    form.display_name.setText("FakeAlt#TEST")
    form.display_name.editingFinished.emit()
    assert (form.display_name.text(), form.tag.text()) == ("FakeAlt", "TEST")


def test_existing_tag_is_never_overwritten(qtbot: Any) -> None:
    form = _form(qtbot)
    form.tag.setText("EUW")
    form.display_name.setText("FakeAlt#TEST")
    form.display_name.editingFinished.emit()
    assert (form.display_name.text(), form.tag.text()) == ("FakeAlt#TEST", "EUW")
