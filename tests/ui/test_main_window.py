"""Main window with a real (demo) vault: sidebar, search, table, masking, delete, lock."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtCore import Qt

from conftest import FAST_KDF
from vaultkeeper import demo
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui import main_window as mw
from vaultkeeper.ui.widgets.account_table import MASK


@pytest.fixture
def unlocked(tmp_path: Path) -> VaultService:
    env = demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock(demo.DEMO_PASSWORD)
    return svc


@pytest.fixture
def window(qtbot: Any, unlocked: VaultService) -> mw.MainWindow:
    win = mw.MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.show_unlocked(str(unlocked.path), False, AccountService(unlocked), GameService(unlocked))
    return win


def _game_id(svc: VaultService, name: str) -> str:
    return next(g.id for g in svc.data.games if g.name == name)


def _column(win: mw.MainWindow, key: str) -> list[str]:
    model, proxy = win.panel.model, win.panel.proxy
    col = model.column_of(key)
    return [proxy.index(r, col).data() for r in range(proxy.rowCount())]


def test_all_games_view(window: mw.MainWindow) -> None:
    sidebar = window.panel.sidebar
    labels = [sidebar.item(i).text() for i in range(sidebar.count())]
    assert labels[0] == "All games (30)"
    assert "Valorant (12)" in labels and "Apex Legends (3)" in labels
    assert window.panel.proxy.rowCount() == 30
    assert window.panel.model.column_of("game") == 0
    assert "30 of 30 accounts" in window.statusBar().currentMessage()


def test_selecting_a_game_groups_accounts(window: mw.MainWindow, unlocked: VaultService) -> None:
    window.panel.sidebar.select_game(_game_id(unlocked, "Valorant"))
    assert window.panel.proxy.rowCount() == 12
    assert window.panel.model.column_of("game") == -1  # no Game column inside one game
    regions = [window.panel.search.region.itemData(i)
               for i in range(1, window.panel.search.region.count())]
    assert regions == ["NA", "EU", "AP", "KR", "LATAM", "BR"]
    assert "12 of 30" in window.statusBar().currentMessage()


def test_search_text_and_filters(window: mw.MainWindow, unlocked: VaultService) -> None:
    search = window.panel.search
    search.text.setText("demoalt01")
    assert _column(window, "name") == ["DemoAlt01"]
    search.reset()
    search.status.setCurrentIndex(search.status.findData("banned"))
    assert set(_column(window, "status")) == {"Banned"}
    search.reset()
    window.panel.sidebar.select_game(_game_id(unlocked, "Valorant"))
    search.rank.setCurrentIndex(search.rank.findData("__unranked__"))
    assert set(_column(window, "rank")) == {"Unranked"}
    search.clear_button.click()
    assert window.panel.proxy.rowCount() == 12


def test_passwords_masked_until_toggled(window: mw.MainWindow) -> None:
    assert set(_column(window, "password")) == {MASK}
    window.show_passwords_action.setChecked(True)
    assert all(p.startswith("Fake-Demo-Pass-") for p in _column(window, "password"))
    window.show_locked()
    assert not window.show_passwords_action.isChecked()


def test_rank_sort_follows_ladder(window: mw.MainWindow, unlocked: VaultService) -> None:
    window.panel.sidebar.select_game(_game_id(unlocked, "Overwatch"))
    col = window.panel.model.column_of("rank")
    window.panel.table.sortByColumn(col, Qt.AscendingOrder)
    ranks = _column(window, "rank")
    assert ranks[0] == "Unranked" and ranks[-1] == "Top 500"
    assert ranks.index("Silver 5") < ranks.index("Platinum 3") < ranks.index("Champion 4")


def test_password_column_never_sorts_by_secret(window: mw.MainWindow) -> None:
    model = window.panel.model
    col = model.column_of("password")
    assert {model.sort_key(r, col) for r in range(model.rowCount())} == {""}


def _select_first(window: mw.MainWindow) -> None:
    window.panel.table.selectRow(0)


def test_delete_needs_selection_and_confirmation(window: mw.MainWindow, unlocked: VaultService,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    assert not window.delete_action.isEnabled()
    _select_first(window)
    assert window.delete_action.isEnabled()
    victim = window.panel.selected_account()
    assert victim is not None

    monkeypatch.setattr(mw, "confirm", lambda *a, **k: False)
    window.delete_action.trigger()
    assert len(unlocked.data.accounts) == 30

    asked: list[str] = []
    monkeypatch.setattr(mw, "confirm", lambda _p, _t, text, **k: asked.append(text) or True)
    window.delete_action.trigger()
    assert len(unlocked.data.accounts) == 29
    assert victim.id not in {a.id for a in unlocked.data.accounts}
    assert victim.riot_id in asked[0]
    assert window.panel.sidebar.item(0).text() == "All games (29)"

    unlocked.lock()
    reopened = VaultService(unlocked.path, kdf_params=FAST_KDF)
    reopened.unlock(demo.DEMO_PASSWORD)
    assert len(reopened.data.accounts) == 29  # saved to disk


def test_backup_banner(qtbot: Any, unlocked: VaultService) -> None:
    win = mw.MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.show_unlocked(str(unlocked.path), True, AccountService(unlocked), GameService(unlocked))
    assert win.banner.isVisible()
    win.show_locked()
    assert win.banner.isHidden()


def test_locked_state_shows_nothing(window: mw.MainWindow) -> None:
    window.show_locked()
    assert window.panel.model.rowCount() == 0
    assert window.panel.sidebar.count() == 0
    assert window.stack.currentWidget() is window.locked_label
    for act in (window.lock_action, window.change_password_action, window.delete_action,
                window.show_passwords_action):
        assert not act.isEnabled()


def test_signals(qtbot: Any, window: mw.MainWindow) -> None:
    with qtbot.waitSignal(window.lock_requested, timeout=1000):
        window.lock_action.trigger()
    with qtbot.waitSignal(window.change_password_requested, timeout=1000):
        window.change_password_action.trigger()


def test_add_edit_games_actions_enabled(window: mw.MainWindow) -> None:
    assert window.add_action.isEnabled() and window.manage_games_action.isEnabled()
    assert not window.edit_action.isEnabled()  # nothing selected yet
    window.panel.table.selectRow(0)
    assert window.edit_action.isEnabled()


def test_edit_opens_dialog_for_selected_account(window: mw.MainWindow,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[object] = []

    class FakeDialog:
        def __init__(self, _accounts: object, _games: object, account: object = None,
                     **_kw: object) -> None:
            opened.append(account)

        def deleteLater(self) -> None:  # noqa: N802 - Qt API (run_modal)
            pass

        def exec_(self) -> int:
            return 0

    monkeypatch.setattr(mw, "AccountDialog", FakeDialog)
    window.panel.table.selectRow(0)
    selected = window.panel.selected_account()
    window.edit_action.trigger()
    assert opened == [selected]


def test_select_account_after_refresh(window: mw.MainWindow, unlocked: VaultService) -> None:
    target = unlocked.data.accounts[5]
    window.panel.refresh()
    assert window.panel.selected_account() is None
    assert window.panel.select_account(target.id)
    assert window.panel.selected_account() == target


def test_custom_game_columns_follow_template(window: mw.MainWindow,
                                             unlocked: VaultService) -> None:
    """Demo's Apex: extra non-secret fields get columns; the secret field never does."""
    window.panel.sidebar.select_game(_game_id(unlocked, "Apex Legends"))
    model = window.panel.model
    headers = [model.headerData(c, Qt.Horizontal) for c in range(model.columnCount())]
    assert "Main legend" in headers and "Account level" in headers
    assert "Backup code" not in headers
    legends = _column_by_header(window, "Main legend")
    assert set(legends) <= {"Wraith", "Bloodhound", "Lifeline"}
    assert not any("FAKE-CODE" in str(model.data(model.index(r, c)))
                   for r in range(model.rowCount()) for c in range(model.columnCount()))


def test_search_finds_extra_fields_but_not_secret_ones(window: mw.MainWindow) -> None:
    window.panel.search.text.setText("bloodhound")
    assert window.panel.proxy.rowCount() >= 1
    window.panel.search.text.setText("FAKE-CODE-0001")
    assert window.panel.proxy.rowCount() == 0


def _column_by_header(win: mw.MainWindow, header: str) -> list[str]:
    model, proxy = win.panel.model, win.panel.proxy
    col = next(c for c in range(model.columnCount())
               if model.headerData(c, Qt.Horizontal) == header)
    return [proxy.index(r, col).data() for r in range(proxy.rowCount())]
