"""Quick Add: keyboard-first batch entry with paste assist.

- Enter (or Ctrl+Enter anywhere) = save and start a fresh form; Esc = close (asks first if
  anything is typed).
- Batch mode: game, region and status carry over to the next entry until changed.
- Paste box: one raw block -> "Fill from paste" fills EMPTY fields only (plus status/notes).
  It never saves: you review every entry and press Enter yourself.
- Live duplicate warning and validation come from AccountDialog.
"""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QShortcut,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.account_service import AccountService
from vaultkeeper.core.entry_session import EntrySession
from vaultkeeper.core.models import Account, Game
from vaultkeeper.core.paste_assist import PasteSuggestions, suggest
from vaultkeeper.ui.account_dialog import AccountDialog
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import MUTED_STYLE

COUNTER_STYLE = "color: #8fd18f; font-weight: bold;"


class QuickAddDialog(AccountDialog):
    """Stays open between entries. Emits ``saved_one(account)`` after each save."""

    saved_one = pyqtSignal(object)

    def __init__(self, accounts: AccountService, games: list[Game], session: EntrySession,
                 default_game_id: str | None = None, parent: QWidget | None = None) -> None:
        self._session = session
        game_id = session.starting_game_id(default_game_id)
        draft = session.next_draft(accounts.new_draft(game_id)) if game_id else None
        super().__init__(accounts, games, default_game_id=game_id, parent=parent, draft=draft)
        self.setWindowTitle("Quick Add")
        self.setMinimumWidth(600)
        self.save_button.setText("Save && next (Enter)")
        self.cancel_button.setText("Close (Esc)")

        self.counter = plain_label(session.counter_text(), self)
        self.counter.setStyleSheet(COUNTER_STYLE)
        hint = plain_label("Batch mode: game, region and status stay set for the next entry.", self)
        hint.setStyleSheet(MUTED_STYLE)
        self.paste_box = QPlainTextEdit(self)
        self.paste_box.setPlaceholderText(
            "Optional: paste one account's text here, then press Fill from paste.\n"
            "e.g.  user: name   pass: ...   email: ...   Name#TAG   gold 2   EU   banned")
        self.paste_box.setTabChangesFocus(True)
        self.paste_box.setFixedHeight(80)
        self.fill_button = QPushButton("Fill from paste", self)
        self.fill_button.setAutoDefault(False)
        self.paste_result = plain_label(parent=self)
        self.paste_result.setWordWrap(True)
        self.paste_result.setStyleSheet(MUTED_STYLE)
        self.saved_label = plain_label(parent=self)
        self.saved_label.setStyleSheet(MUTED_STYLE)

        top = QHBoxLayout()
        top.addWidget(hint, 1)
        top.addWidget(self.counter)
        paste_row = QHBoxLayout()
        paste_row.addWidget(self.paste_box, 1)
        paste_row.addWidget(self.fill_button)
        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)  # noqa: S101 - built by AccountDialog
        layout.insertLayout(0, top)
        layout.insertLayout(layout.count() - 1, paste_row)
        layout.insertWidget(layout.count() - 1, self.paste_result)
        layout.insertWidget(layout.count() - 1, self.saved_label)

        self.fill_button.clicked.connect(self.fill_from_paste)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._save)
        # Multi-line boxes swallow Ctrl+Enter before shortcuts see it, so catch it there.
        for box in (self.form.notes, self.paste_box):
            box.installEventFilter(self)
        self._focus_first_field()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        """Ctrl+Enter in Notes or the paste box saves (plain Enter still adds a new line)."""
        if (event.type() == QEvent.KeyPress
                and event.key() in (Qt.Key_Return, Qt.Key_Enter)  # type: ignore[attr-defined]
                and event.modifiers() & Qt.ControlModifier):  # type: ignore[attr-defined]
            self._save()
            return True
        return super().eventFilter(obj, event)

    # --- saving: stay open with a fresh form ------------------------------------------------

    def _saved_ok(self, stored: Account) -> None:
        self.saved = stored
        self._session.remember(stored)
        self.saved_one.emit(stored)
        fresh = self._session.next_draft(self._accounts.new_draft(stored.game_id))
        self._base = fresh
        self.form.load(fresh)
        self.paste_box.clear()
        self.paste_result.clear()
        self._initial = self._snapshot()
        self.counter.setText(self._session.counter_text())
        label = stored.riot_id or stored.login_username or stored.email
        self.saved_label.setText(f"Saved {label}. Ready for the next one.")
        self._focus_first_field()

    def _focus_first_field(self) -> None:
        form = self.form
        if not form.has_game:
            form.game.setFocus()
        else:
            (form.display_name if form.display_name.isVisible() else form.login).setFocus()

    # --- paste assist -----------------------------------------------------------------------

    def fill_from_paste(self) -> PasteSuggestions | None:
        """Fill empty fields from the paste box. Never saves."""
        game = self.form.current_game
        if game is None:
            self.paste_result.setText("Choose a game first, so ranks and regions match it.")
            return None
        found = suggest(self.paste_box.toPlainText(), game.template)
        filled = self._apply(found)
        parts = [f"Filled: {', '.join(filled)}." if filled else "Nothing new to fill."]
        parts += found.warnings
        parts.append("Review, then press Enter to save.")
        self.paste_result.setText(" ".join(parts))
        return found

    def _apply(self, found: PasteSuggestions) -> list[str]:
        form, fields, filled = self.form, found.fields, []
        text_targets = {
            "display_name": form.display_name, "tag": form.tag, "login_username": form.login,
            "password": form.password, "email": form.email,
            "email_password": form.email_password, "recovery_email": form.recovery_email,
        }  # fmt: skip
        for key, widget in text_targets.items():
            if key in fields and not widget.text():
                widget.setText(fields[key])
                filled.append(_NAMES[key])
        if "region" in fields and form.region.region() is None:
            form.region.set_region(fields["region"])
            filled.append("region")
        if "rank" in fields and form.rank.rank().is_unranked:
            form.rank.set_rank(fields["rank"])
            filled.append("rank")
        if "status" in fields:
            form.status.setCurrentIndex(max(form.status.findData(fields["status"]), 0))
            filled.append("status")
        if found.notes:
            existing = form.notes.toPlainText().strip()
            form.notes.setPlainText("\n".join([existing, *found.notes]).strip())
            filled.append("notes")
        for field_id, value in found.extra.items():
            widget = form.extra_widget(field_id)
            if isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index > 0 and widget.currentIndex() == 0:
                    widget.setCurrentIndex(index)
                    filled.append("extra field")
            elif widget is not None and not widget.text():  # QLineEdit or SecretField
                widget.setText(value)
                filled.append("extra field")
        return filled


_NAMES = {
    "display_name": "name", "tag": "tag", "login_username": "username", "password": "password",
    "email": "email", "email_password": "email password", "recovery_email": "recovery email",
}  # fmt: skip
