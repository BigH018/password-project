"""The account form fields. Reads/writes an Account; validation happens in core on save."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QWidget,
)

from vaultkeeper.config.constants import STATUSES, get_preset
from vaultkeeper.core.models import Account, Game
from vaultkeeper.ui.widgets.rank_picker import RankPicker, RegionPicker
from vaultkeeper.ui.widgets.secret_field import SecretField


class AccountForm(QWidget):
    """All editable account fields in keyboard order. Emits ``changed`` on any edit."""

    changed = pyqtSignal()

    def __init__(self, games: list[Game], parent: Any = None) -> None:
        super().__init__(parent)
        self._games = {g.id: g for g in games}
        self.game = QComboBox(self)
        for game in games:
            self.game.addItem(game.name, game.id)
        self.display_name = QLineEdit(self)
        self.display_name.setPlaceholderText("In-game name / Riot ID name")
        self.tag = QLineEdit(self)
        self.tag.setPlaceholderText("Tag")
        self.tag.setMaximumWidth(110)
        self.login = QLineEdit(self)
        self.password = SecretField("Account password", self)
        self.email = QLineEdit(self)
        self.email_password = SecretField("Email password (optional)", self)
        self.email_url = QLineEdit(self)
        self.email_url.setPlaceholderText("https://... (optional, copy-only)")
        self.region = RegionPicker(self)
        self.rank = RankPicker(self)
        self.status = QComboBox(self)
        for status in STATUSES:
            self.status.addItem(status.capitalize(), status)
        self.recovery_email = QLineEdit(self)
        self.tags = QLineEdit(self)
        self.tags.setPlaceholderText("Comma-separated, e.g. main, smurf")
        self.notes = QPlainTextEdit(self)
        self.notes.setTabChangesFocus(True)
        self.notes.setFixedHeight(80)

        name_row = QHBoxLayout()
        name_row.addWidget(self.display_name, 1)
        name_row.addWidget(QLabel("#", self))
        name_row.addWidget(self.tag)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Game", self.game)
        form.addRow("Name", name_row)
        form.addRow("Login", self.login)
        form.addRow("Password", self.password)
        form.addRow("Email", self.email)
        form.addRow("Email password", self.email_password)
        form.addRow("Email login URL", self.email_url)
        form.addRow("Region", self.region)
        form.addRow("Rank", self.rank)
        form.addRow("Status", self.status)
        form.addRow("Recovery email", self.recovery_email)
        form.addRow("Labels", self.tags)
        form.addRow("Notes", self.notes)

        self.game.currentIndexChanged.connect(self._game_changed)
        for edit in (self.display_name, self.tag, self.login, self.email, self.email_url,
                     self.recovery_email, self.tags):
            edit.textChanged.connect(self.changed)
        for widget in (self.password, self.email_password):
            widget.textChanged.connect(self.changed)
        for picker in (self.region, self.rank):
            picker.changed.connect(self.changed)
        self.status.currentIndexChanged.connect(self.changed)
        self.notes.textChanged.connect(self.changed)

    # --- game / preset ------------------------------------------------------------------

    def _current_game(self) -> Game | None:
        return self._games.get(self.game.currentData())

    def _game_changed(self) -> None:
        game = self._current_game()
        if game is not None:
            preset = get_preset(game.preset)
            self.region.set_preset(preset)
            self.rank.set_preset(preset)
        self.changed.emit()

    # --- load / read --------------------------------------------------------------------

    def load(self, account: Account) -> None:
        """Fill every field from ``account``."""
        self.game.blockSignals(True)
        self.game.setCurrentIndex(max(self.game.findData(account.game_id), 0))
        self.game.blockSignals(False)
        game = self._current_game()
        preset = get_preset(game.preset if game else "")
        self.region.set_preset(preset, keep=account.region, use_current=False)
        self.rank.set_preset(preset, keep=account.rank)
        self.display_name.setText(account.display_name)
        self.tag.setText(account.tag or "")
        self.login.setText(account.login_username)
        self.password.setText(account.password)
        self.email.setText(account.email)
        self.email_password.setText(account.email_password or "")
        self.email_url.setText(account.email_login_url or "")
        self.status.setCurrentIndex(max(self.status.findData(account.status), 0))
        self.recovery_email.setText(account.recovery_email or "")
        self.tags.setText(", ".join(account.tags))
        self.notes.setPlainText(account.notes)

    def to_account(self, base: Account) -> Account:
        """``base`` with the form's values (raw; core validates and normalizes)."""
        return replace(
            base,
            game_id=self.game.currentData() or base.game_id,
            display_name=self.display_name.text(),
            tag=self.tag.text() or None,
            login_username=self.login.text(),
            password=self.password.text(),
            email=self.email.text(),
            email_password=self.email_password.text() or None,
            email_login_url=self.email_url.text() or None,
            region=self.region.region(),
            rank=self.rank.rank(),
            status=self.status.currentData(),
            recovery_email=self.recovery_email.text() or None,
            tags=tuple(t for t in (p.strip() for p in self.tags.text().split(",")) if t),
            notes=self.notes.toPlainText(),
        )

    def game_name(self, game_id: str) -> str:
        """Display name of a game (for messages)."""
        game = self._games.get(game_id)
        return game.name if game else ""
