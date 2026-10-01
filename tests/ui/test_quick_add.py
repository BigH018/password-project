"""Quick Add: save-and-next, batch stickiness, counter, paste assist (never saves), keys."""

from __future__ import annotations

from typing import Any

import pytest
from PyQt5.QtCore import Qt

from conftest import FakeStore
from fake_data import make_game
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.entry_session import EntrySession
from vaultkeeper.core.models import Game, Rank
from vaultkeeper.ui import quick_add_dialog as qa


@pytest.fixture
def games(store: FakeStore) -> list[Game]:
    val, ow = make_game("Valorant", "valorant"), make_game("Overwatch", "overwatch")
    store.data.games.extend([val, ow])
    return [val, ow]


@pytest.fixture
def accounts(store: FakeStore) -> AccountService:
    return AccountService(store)


def _open(qtbot: Any, accounts: AccountService, games: list[Game], session: EntrySession,
          **kw: Any) -> qa.QuickAddDialog:
    dialog = qa.QuickAddDialog(accounts, games, session, **kw)
    qtbot.addWidget(dialog)
    dialog.show()
    return dialog


def test_save_and_next_keeps_dialog_open(qtbot: Any, accounts: AccountService,
                                         games: list[Game]) -> None:
    session = EntrySession()
    dialog = _open(qtbot, accounts, games, session, default_game_id=games[0].id)
    saved: list[Any] = []
    dialog.saved_one.connect(saved.append)
    dialog.form.login.setText("fake_batch_1")
    dialog.form.region.set_region("EU")
    dialog.form.status.setCurrentIndex(dialog.form.status.findData("banned"))
    dialog.save_button.click()
    assert dialog.isVisible() and len(saved) == 1
    assert dialog.counter.text() == "1 added this session"
    # Fresh form, but batch values stick.
    assert dialog.form.login.text() == ""
    assert dialog.form.region.region() == "EU"
    assert dialog.form.status.currentData() == "banned"
    assert dialog.form.game.currentData() == games[0].id
    assert not dialog.has_changes  # a fresh form isn't an "unsaved draft"
    dialog.form.login.setText("fake_batch_2")
    dialog.save_button.click()
    assert dialog.counter.text() == "2 added this session"
    assert len(accounts.list_all()) == 2


def test_enter_saves(qtbot: Any, accounts: AccountService, games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games, EntrySession(), default_game_id=games[0].id)
    dialog.form.login.setText("fake_enter_login")
    qtbot.keyPress(dialog.form.login, Qt.Key_Return)
    assert len(accounts.list_all()) == 1 and dialog.isVisible()


def test_ctrl_enter_saves_from_notes(qtbot: Any, accounts: AccountService,
                                     games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games, EntrySession(), default_game_id=games[0].id)
    dialog.form.login.setText("fake_notes_login")
    dialog.form.notes.setFocus()
    qtbot.keyPress(dialog.form.notes, Qt.Key_Return, Qt.ControlModifier)
    assert len(accounts.list_all()) == 1


def test_session_survives_reopening(qtbot: Any, accounts: AccountService,
                                    games: list[Game]) -> None:
    session = EntrySession()
    first = _open(qtbot, accounts, games, session, default_game_id=games[1].id)
    first.form.login.setText("fake_ow_1")
    first.form.region.set_region("Europe")
    first.save_button.click()
    first.force_close()
    second = _open(qtbot, accounts, games, session)  # "All games" view: no default game
    assert second.form.game.currentData() == games[1].id  # batch game remembered
    assert second.form.region.region() == "Europe"
    assert second.counter.text() == "1 added this session"


def test_paste_fills_but_never_saves(qtbot: Any, accounts: AccountService,
                                     games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games, EntrySession(), default_game_id=games[0].id)
    dialog.paste_box.setPlainText(
        "user: fake_paste_login\npass: Fake-Paste-Pass-1\nFakeAlt#EUW1 alt@example.test\n"
        "imm 2 kr banned")
    found = dialog.fill_from_paste()
    assert found is not None
    form = dialog.form
    assert form.login.text() == "fake_paste_login"
    assert form.password.text() == "Fake-Paste-Pass-1" and not form.password.revealed
    assert (form.display_name.text(), form.tag.text()) == ("FakeAlt", "EUW1")
    assert form.email.text() == "alt@example.test"
    assert form.rank.rank() == Rank("Immortal", 2) and form.region.region() == "KR"
    assert form.status.currentData() == "banned"
    assert "Banned (from pasted text)." in form.notes.toPlainText()
    assert accounts.list_all() == []  # nothing saved until you press Enter
    summary = dialog.paste_result.text()
    assert "Filled:" in summary and "press Enter to save" in summary
    assert "Fake-Paste-Pass-1" not in summary


def test_paste_never_overwrites_typed_values(qtbot: Any, accounts: AccountService,
                                             games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games, EntrySession(), default_game_id=games[0].id)
    dialog.form.login.setText("typed_by_hand")
    dialog.paste_box.setPlainText("user: from_paste\nemail: p@example.test")
    dialog.fill_from_paste()
    assert dialog.form.login.text() == "typed_by_hand"
    assert dialog.form.email.text() == "p@example.test"


def test_paste_needs_a_game(qtbot: Any, accounts: AccountService, games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games, EntrySession())  # placeholder game
    dialog.paste_box.setPlainText("user: someone")
    assert dialog.fill_from_paste() is None
    assert "Choose a game first" in dialog.paste_result.text()


def test_duplicate_warning_in_quick_add(qtbot: Any, accounts: AccountService,
                                        games: list[Game]) -> None:
    dialog = _open(qtbot, accounts, games, EntrySession(), default_game_id=games[0].id)
    dialog.form.login.setText("dupe_login")
    dialog.save_button.click()
    dialog.form.login.setText("DUPE_LOGIN")
    assert "same login" in dialog.duplicate_label.text()


def test_esc_with_draft_asks(qtbot: Any, accounts: AccountService, games: list[Game],
                             monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    from vaultkeeper.ui import account_dialog

    monkeypatch.setattr(account_dialog.messages, "confirm",
                        lambda *_a, **_k: asked.append("asked") or False)
    dialog = _open(qtbot, accounts, games, EntrySession(), default_game_id=games[0].id)
    dialog.form.login.setText("half typed")
    qtbot.keyPress(dialog, Qt.Key_Escape)
    assert asked == ["asked"] and dialog.isVisible()


def test_main_window_quick_add_uses_longer_autolock(qtbot: Any, tmp_path: Any,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from conftest import FAST_KDF
    from vaultkeeper import demo
    from vaultkeeper.config.settings import Settings
    from vaultkeeper.core.vault_service import VaultService
    from vaultkeeper.ui import app_controller, main_window
    from vaultkeeper.ui.qt_adapters import QtTaskRunner

    env = demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock(demo.DEMO_PASSWORD)
    settings = Settings(autolock_minutes=5, quick_add_autolock_minutes=15)
    controller = app_controller.AppController(settings, tmp_path / "s.json", QtTaskRunner(),
                                              lambda p: svc)
    qtbot.addWidget(controller.window)
    controller.service = svc
    controller._show_unlocked()
    timeouts: list[float] = []

    class FakeQuickAdd:
        def __init__(self, *_a: Any, **_k: Any) -> None:
            self.saved_one = type("S", (), {"connect": lambda *_: None})()

        def deleteLater(self) -> None:  # noqa: N802 - Qt API (run_modal)
            pass

        def exec_(self) -> int:
            timeouts.append(controller.guard.tracker.timeout)
            return 0

    monkeypatch.setattr(main_window, "QuickAddDialog", FakeQuickAdd)
    controller.window.quick_add_action.trigger()
    assert timeouts == [15 * 60]  # longer while Quick Add is open
    assert controller.guard.tracker.timeout == 5 * 60  # back to normal afterwards


def test_pasted_password_reaches_the_form_unchanged(qtbot: Any, accounts: AccountService,
                                                    games: list[Game]) -> None:
    decomposed = "Fake-Pa" + "e" + chr(0x301) + "ssw0rd-1!"  # combining accent, not NFC
    dialog = _open(qtbot, accounts, games, EntrySession(), default_game_id=games[0].id)
    dialog.paste_box.setPlainText(f"user: fake_login_nfc\npass: {decomposed}")
    dialog.fill_from_paste()
    assert dialog.form.password.text() == decomposed
    dialog.save_button.click()
    assert accounts.list_all()[0].password == decomposed
