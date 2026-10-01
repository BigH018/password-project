"""Phase 5 UI: copy actions, session guard (auto-lock), generator, backups-off banner."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtWidgets import QDialog

from conftest import FAST_KDF
from test_clipboard import FakeClipboard, FakeTimer
from vaultkeeper import demo
from vaultkeeper.config.settings import Settings
from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.security.autolock import InactivityTracker
from vaultkeeper.security.clipboard import ClipboardGuard
from vaultkeeper.ui import main_window as mw
from vaultkeeper.ui.generator_dialog import GeneratorDialog
from vaultkeeper.ui.session_guard import SessionGuard


def _scheduler(timers: list[FakeTimer]) -> Callable[[float, Callable[[], None]], FakeTimer]:
    def schedule(seconds: float, fn: Callable[[], None]) -> FakeTimer:
        timers.append(FakeTimer(seconds, fn))
        return timers[-1]
    return schedule


@pytest.fixture
def unlocked(tmp_path: Path) -> VaultService:
    env = demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock(demo.DEMO_PASSWORD)
    return svc


@pytest.fixture
def board() -> FakeClipboard:
    return FakeClipboard()


@pytest.fixture
def window(qtbot: Any, unlocked: VaultService, board: FakeClipboard) -> mw.MainWindow:
    win = mw.MainWindow()
    qtbot.addWidget(win)
    win.show()
    win.copy.clipboard = ClipboardGuard(board, _scheduler([]), clear_after=15)
    win.show_unlocked(str(unlocked.path), False, AccountService(unlocked), GameService(unlocked))
    return win


# --- copy -----------------------------------------------------------------------------------


def test_copy_password_and_username(window: mw.MainWindow, board: FakeClipboard) -> None:
    window.panel.table.selectRow(0)
    account = window.panel.selected_account()
    assert account is not None
    window.copy.copy_password.trigger()
    assert board.value == account.password
    message = window.statusBar().currentMessage()
    assert message == "Password copied. The clipboard clears in 15 s."
    assert account.password not in message
    window.copy.copy_login.trigger()
    assert board.value == account.login_username


def test_copy_actions_need_a_selection(window: mw.MainWindow) -> None:
    assert not window.copy.copy_password.isEnabled()
    window.panel.table.selectRow(0)
    assert window.copy.copy_password.isEnabled()


def test_copy_empty_value_explains(window: mw.MainWindow, board: FakeClipboard) -> None:
    window.copy.copy_value("", "Email password")
    assert board.value == ""
    assert "No email password saved" in window.statusBar().currentMessage()


def test_context_menu_offers_secret_extra_fields(window: mw.MainWindow, unlocked: VaultService,
                                                 board: FakeClipboard) -> None:
    apex = next(g for g in unlocked.data.games if g.name == "Apex Legends")
    account = next(a for a in unlocked.data.accounts if a.game_id == apex.id)
    menu = window.copy.build_menu(account, window.context_extra_actions())
    texts = [a.text() for a in menu.actions() if a.text()]
    assert "Copy Backup code" in texts and "Edit" in texts
    window.copy.extra_menu_actions[0].trigger()
    assert board.value.startswith("FAKE-CODE-")
    assert "Backup code copied" in window.statusBar().currentMessage()


# --- session guard ---------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def guard(qapp: Any, board: FakeClipboard) -> SessionGuard:
    g = SessionGuard(Settings(autolock_minutes=5), backend=board, schedule=_scheduler([]))
    return g


def test_inactivity_lock_only_while_armed(qtbot: Any, guard: SessionGuard) -> None:
    clock = Clock()
    guard.tracker = InactivityTracker(300, clock)
    reasons: list[str] = []
    guard.lock_needed.connect(reasons.append)
    clock.now = 10_000
    guard._check()
    assert reasons == []  # locked already: nothing to do
    guard.arm()
    clock.now += 299
    guard._check()
    assert reasons == []
    clock.now += 1
    guard._check()
    assert reasons == ["inactivity"]


def test_minimize_lock_respects_setting(qtbot: Any, board: FakeClipboard) -> None:
    on = SessionGuard(Settings(lock_on_minimize=True), backend=board, schedule=_scheduler([]))
    off = SessionGuard(Settings(lock_on_minimize=False), backend=board, schedule=_scheduler([]))
    seen: list[str] = []
    on.lock_needed.connect(seen.append)
    off.lock_needed.connect(lambda r: seen.append("off:" + r))
    on.arm()
    off.arm()
    on.window_minimized()
    off.window_minimized()
    assert seen == ["minimized"]


def test_disarm_clears_our_clipboard(guard: SessionGuard, board: FakeClipboard) -> None:
    guard.arm()
    guard.clipboard.copy("Fake-Passw0rd-1!")
    guard.disarm()
    assert board.value == "" and not guard.armed


def test_activity_filter_resets_idle(qtbot: Any, guard: SessionGuard) -> None:
    clock = Clock()
    guard.tracker = InactivityTracker(300, clock)
    guard._filter._on_activity = guard.tracker.record_activity
    clock.now = 500
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QKeyEvent

    key = QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier)
    guard._filter.eventFilter(None, key)  # type: ignore[arg-type]
    assert guard.tracker.seconds_idle() == 0


def test_window_emits_minimized(qtbot: Any, window: mw.MainWindow) -> None:
    with qtbot.waitSignal(window.minimized, timeout=2000):
        window.showMinimized()


# --- generator --------------------------------------------------------------------------------


def test_generator_dialog_options_copy_and_use(qtbot: Any) -> None:
    copied: list[str] = []
    dialog = GeneratorDialog(copy=copied.append, allow_use=True)
    qtbot.addWidget(dialog)
    dialog.length.setValue(32)
    dialog.symbols.setChecked(False)
    first = dialog.preview.text()
    assert len(first) == 32 and first.isalnum()
    dialog.regenerate_button.click()
    assert dialog.preview.text() != first
    dialog.copy_button.click()
    assert copied == [dialog.preview.text()]
    chosen = dialog.preview.text()
    dialog.use_button.click()
    assert dialog.result() == QDialog.Accepted and dialog.password == chosen
    assert dialog.preview.text() == ""  # cleared on close


def test_generator_no_character_types(qtbot: Any) -> None:
    dialog = GeneratorDialog()
    qtbot.addWidget(dialog)
    for box in (dialog.lower, dialog.upper, dialog.digits, dialog.symbols):
        box.setChecked(False)
    assert dialog.preview.text() == "" and not dialog.copy_button.isEnabled()
    assert "at least one kind" in dialog.error_label.text().lower()


def test_account_form_generate_fills_password(qtbot: Any, unlocked: VaultService,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from vaultkeeper.ui.widgets import account_form

    class FakeGenerator:
        def __init__(self, **_kw: Any) -> None:
            self.password = "Generated-Fake-Pass-77"

        def deleteLater(self) -> None:  # noqa: N802 - Qt API (run_modal)
            pass

        def exec_(self) -> int:
            return 1

    monkeypatch.setattr(account_form, "GeneratorDialog", FakeGenerator)
    form = account_form.AccountForm(list(unlocked.data.games))
    qtbot.addWidget(form)
    form.generate_button.click()
    assert form.password.text() == "Generated-Fake-Pass-77" and not form.password.revealed




def test_backups_off_banner(window: mw.MainWindow) -> None:
    window.set_backups_enabled(False)
    assert window.backups_off.isVisible()
    window.set_backups_enabled(True)
    assert window.backups_off.isHidden()










