"""User data is never rendered as HTML (SEC-H1).

Qt's default text format (AutoText) renders anything that looks like HTML. A name such as
``<img src=//host/x>`` would then try to load an image, which on Windows can open an
outbound SMB connection. Labels and message boxes that can show user data must be plain text.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLabel, QMessageBox, QWidget

from conftest import FakeStore
from fake_data import make_account, make_game
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.entry_session import EntrySession
from vaultkeeper.core.game_template import CustomField
from vaultkeeper.core.models import Game
from vaultkeeper.ui import account_dialog as ad
from vaultkeeper.ui import quick_add_dialog as qa
from vaultkeeper.ui.error_dialog import build_error_box
from vaultkeeper.ui.messages import confirm as real_confirm  # bound before the autouse stub
from vaultkeeper.ui.messages import show_error as real_show_error

HTML_NAME = "<img src=//fake.invalid/x>"
HTML_LOGIN = "<b>fake_login</b>"
HTML_LABEL = "<i>Fake level</i>"


@pytest.fixture
def html_game(store: FakeStore) -> Game:
    game = make_game("Valorant", "valorant")
    extra = CustomField(id="f1", label=HTML_LABEL)
    game = dataclasses.replace(
        game, template=dataclasses.replace(game.template, custom_fields=(extra,)))
    store.data.games.append(game)
    return game


@pytest.fixture
def html_account(store: FakeStore, html_game: Game) -> Any:
    account = make_account(html_game, display_name=HTML_NAME, tag=None,
                           login_username=HTML_LOGIN)
    store.data.accounts.append(account)
    return account


def _html_labels_are_plain(widget: QWidget) -> None:
    labels = [lbl for lbl in widget.findChildren(QLabel) if "<" in lbl.text()]
    assert labels, "expected at least one label showing the HTML-looking user data"
    for label in labels:
        assert label.textFormat() == Qt.PlainText, f"rich text label: {label.text()!r}"


def test_account_dialog_shows_user_data_as_plain_text(
        qtbot: Any, store: FakeStore, html_game: Game, html_account: Any) -> None:
    accounts = AccountService(store)
    dialog = ad.AccountDialog(accounts, [html_game], default_game_id=html_game.id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.form.login.setText(HTML_LOGIN)  # duplicate warning names the other account
    assert HTML_NAME in dialog.duplicate_label.text() or HTML_LOGIN in \
        dialog.duplicate_label.text()
    _html_labels_are_plain(dialog)


def test_extra_field_label_is_plain_text(qtbot: Any, store: FakeStore, html_game: Game) -> None:
    dialog = ad.AccountDialog(AccountService(store), [html_game], default_game_id=html_game.id)
    qtbot.addWidget(dialog)
    dialog.show()
    widget = dialog.form._extra_widgets["f1"][1]
    label = dialog.form.extra_layout.labelForField(widget)
    assert isinstance(label, QLabel) and label.text() == HTML_LABEL
    assert label.textFormat() == Qt.PlainText


def test_quick_add_saved_label_is_plain_text(qtbot: Any, store: FakeStore,
                                             html_game: Game) -> None:
    dialog = qa.QuickAddDialog(AccountService(store), [html_game], EntrySession(),
                               default_game_id=html_game.id)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.form.display_name.setText(HTML_NAME)
    dialog.save_button.click()
    assert HTML_NAME in dialog.saved_label.text()
    _html_labels_are_plain(dialog)


@pytest.fixture
def captured_boxes(monkeypatch: pytest.MonkeyPatch) -> list[QMessageBox]:
    """Record message boxes instead of showing them; static helpers can't be made plain."""
    boxes: list[QMessageBox] = []

    def fake_exec(self: QMessageBox) -> int:
        boxes.append(self)
        return 0

    def no_static(*_a: Any, **_k: Any) -> None:
        raise AssertionError("static QMessageBox helpers render rich text")

    monkeypatch.setattr(QMessageBox, "exec_", fake_exec)
    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    for name in ("critical", "warning", "information", "question"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(no_static))
    return boxes


def test_confirm_is_plain_text(qapp: Any, captured_boxes: list[QMessageBox]) -> None:
    assert real_confirm(None, "Delete account", f"Delete {HTML_NAME}?") is False
    assert captured_boxes[0].textFormat() == Qt.PlainText
    assert HTML_NAME in captured_boxes[0].text()


def test_show_error_is_plain_text(qapp: Any, captured_boxes: list[QMessageBox]) -> None:
    real_show_error(None, "Could not delete", f"Problem with {HTML_NAME}")
    assert captured_boxes[0].textFormat() == Qt.PlainText


def test_error_notice_is_plain_text(qapp: Any, tmp_path: Path) -> None:
    box = build_error_box(tmp_path / "<i>logs")
    try:
        assert box.textFormat() == Qt.PlainText
        informative = box.findChild(QLabel, "qt_msgbox_informativelabel")
        assert informative is not None and "<i>logs" in informative.text()
        assert informative.textFormat() == Qt.PlainText
    finally:
        box.deleteLater()


def test_backups_off_link_still_works(qtbot: Any) -> None:
    from vaultkeeper.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    assert window.backups_off.textFormat() == Qt.RichText  # fixed app text with a link
    assert not window.backups_off.openExternalLinks()
    with qtbot.waitSignal(window.backups_requested):
        window.backups_off.linkActivated.emit("setup")
