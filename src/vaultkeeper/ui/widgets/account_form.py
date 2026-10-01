"""The account form, built from the selected game's template.

Standard fields the template hides are hidden (their values are kept, not cleared). Extra
fields are generated from the template. Values for fields the game no longer has are passed
through unchanged, so nothing is deleted silently. Validation happens in core on save.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QWidget,
)

from vaultkeeper.config.constants import STATUSES
from vaultkeeper.core.game_template import CustomField, FieldKind, GameTemplate
from vaultkeeper.core.models import Account, Game, Rank
from vaultkeeper.core.validation import split_name_and_tag
from vaultkeeper.ui.generator_dialog import GeneratorDialog
from vaultkeeper.ui.messages import run_modal
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.widgets.rank_picker import NOT_IN_LIST, RankPicker, RegionPicker
from vaultkeeper.ui.widgets.secret_field import SecretField

ExtraWidget = QLineEdit | QComboBox | SecretField


class AccountForm(QWidget):
    """All account fields in keyboard order. Emits ``changed`` on any edit."""

    changed = pyqtSignal()

    def __init__(self, games: list[Game], require_game_choice: bool = False,
                 parent: Any = None) -> None:
        super().__init__(parent)
        self._games = {g.id: g for g in games}
        self._base_game_id = ""
        self._base_extra: dict[str, str] = {}
        self._base_rank, self._base_region = Rank(), None  # the stored account's values
        self._extra_widgets: dict[str, tuple[CustomField, ExtraWidget]] = {}

        self.game = QComboBox(self)
        if require_game_choice:  # no silent default: the user picks the game explicitly
            self.game.addItem("Choose a game...", None)
        for game in games:
            self.game.addItem(game.name, game.id)
        self.display_name = QLineEdit(self)
        self.display_name.setPlaceholderText("In-game name / Riot ID name")
        self.hash_label = plain_label("#", self)
        self.tag = QLineEdit(self)
        self.tag.setPlaceholderText("Tag")
        self.tag.setMaximumWidth(110)
        self.login = QLineEdit(self)
        self.password = SecretField("Account password", self)
        self.generate_button = QPushButton("Generate...", self)
        self.generate_button.setToolTip("Create a strong random password")
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
        self.extra_box = QWidget(self)
        self.extra_layout = QFormLayout(self.extra_box)
        self.extra_layout.setContentsMargins(0, 0, 0, 0)

        name_row = QHBoxLayout()
        name_row.addWidget(self.display_name, 1)
        name_row.addWidget(self.hash_label)
        name_row.addWidget(self.tag)
        password_row = QHBoxLayout()
        password_row.addWidget(self.password, 1)
        password_row.addWidget(self.generate_button)
        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        for label, widget in (
            ("Game", self.game), ("Name", name_row), ("Login", self.login),
            ("Password", password_row), ("Email", self.email),
            ("Email password", self.email_password), ("Email login URL", self.email_url),
            ("Region", self.region), ("Rank", self.rank), ("Status", self.status),
            ("Recovery email", self.recovery_email), ("Labels", self.tags), ("Notes", self.notes),
        ):  # fmt: skip
            self.form.addRow(plain_label(label, self), widget)
        self.form.addRow(self.extra_box)
        # Optional standard field -> widgets to hide with it.
        self._optional = {
            "tag": [self.tag, self.hash_label], "region": [self.region], "rank": [self.rank],
            "email_password": [self.email_password], "email_login_url": [self.email_url],
            "recovery_email": [self.recovery_email],
        }  # fmt: skip

        self.game.currentIndexChanged.connect(self._game_changed)
        self.display_name.editingFinished.connect(self._split_name_and_tag)
        self.generate_button.clicked.connect(self._generate_password)
        for edit in (self.display_name, self.tag, self.login, self.email, self.email_url,
                     self.recovery_email, self.tags):
            edit.textChanged.connect(self.changed)
        for widget in (self.password, self.email_password):
            widget.textChanged.connect(self.changed)
        for picker in (self.region, self.rank):
            picker.changed.connect(self.changed)
        self.status.currentIndexChanged.connect(self.changed)
        self.notes.textChanged.connect(self.changed)

    def _split_name_and_tag(self) -> None:
        """Typed "name#tag" with the tag empty: show it split, as saving would store it."""
        name, tag = split_name_and_tag(self.display_name.text(), self.tag.text())
        if name != self.display_name.text():
            self.display_name.setText(name)
            self.tag.setText(tag or "")

    def _generate_password(self) -> None:
        dialog = GeneratorDialog(allow_use=True, parent=self)
        if run_modal(dialog) and dialog.password:
            self.password.setText(dialog.password)

    # --- game / template --------------------------------------------------------------------

    @property
    def current_game(self) -> Game | None:
        """The selected game (None while "Choose a game..." is showing)."""
        return self._games.get(self.game.currentData())

    @property
    def has_game(self) -> bool:
        """Whether a real game (not the "Choose a game..." placeholder) is selected."""
        return self.current_game is not None

    def _game_changed(self) -> None:
        self._apply_template(keep_extra=self._extra_values())
        self.changed.emit()

    def _apply_template(self, keep_extra: dict[str, str], account: Account | None = None) -> None:
        game = self.current_game
        template = game.template if game else GameTemplate()
        self.region.setEnabled(game is not None)
        self.rank.setEnabled(game is not None)
        if game is not None:
            preset = game.rank_preset
            if account is not None:
                self.region.set_preset(preset, keep=account.region, use_current=False)
                self.rank.set_preset(preset, keep=account.rank)
            else:  # the user picked another game
                self._switch_pickers(game)
        for key, widgets in self._optional.items():
            visible = template.shows(key)
            for widget in widgets:
                widget.setVisible(visible)
            label = self.form.labelForField(widgets[0])
            if label is not None and key != "tag":
                label.setVisible(visible)
        self._build_extras(template.custom_fields, keep_extra)

    def _switch_pickers(self, game: Game) -> None:
        """Keep rank/region only if the new game lists them. Values outside the list are
        kept only for the account's own stored game, so they never move to another game."""
        preset = game.rank_preset
        self.region.set_preset(preset, listed_only=True)
        self.rank.set_preset(preset, listed_only=True)
        if game.id == self._base_game_id:
            if self.region.region() is None:
                self.region.set_region(self._base_region)
            if self.rank.rank().tier is None:
                self.rank.set_rank(self._base_rank)

    def _build_extras(self, fields: tuple[CustomField, ...], values: dict[str, str]) -> None:
        while self.extra_layout.rowCount():
            self.extra_layout.removeRow(0)
        self._extra_widgets.clear()
        for custom in fields:
            widget = self._make_extra_widget(custom, values.get(custom.id, ""))
            self._extra_widgets[custom.id] = (custom, widget)
            self.extra_layout.addRow(plain_label(custom.label, self.extra_box), widget)
        self.extra_box.setVisible(bool(fields))

    def _make_extra_widget(self, custom: CustomField, value: str) -> ExtraWidget:
        widget: ExtraWidget
        if custom.kind is FieldKind.SECRET:
            widget = SecretField(custom.label, self)
            widget.setText(value)
            widget.textChanged.connect(self.changed)
        elif custom.kind is FieldKind.CHOICE:
            widget = QComboBox(self)
            widget.addItem("(none)", "")
            for option in custom.choices:
                widget.addItem(option, option)
            if value and value not in custom.choices:
                widget.addItem(value + NOT_IN_LIST, value)
            widget.setCurrentIndex(max(widget.findData(value), 0))
            widget.currentIndexChanged.connect(self.changed)
        else:
            widget = QLineEdit(value, self)
            if custom.kind is FieldKind.NUMBER:
                widget.setPlaceholderText("A number")
            widget.textChanged.connect(self.changed)
        return widget

    def extra_widget(self, field_id: str) -> ExtraWidget | None:
        """The input widget for an extra field (None if the game doesn't have it)."""
        entry = self._extra_widgets.get(field_id)
        return entry[1] if entry else None

    def _extra_values(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for field_id, (_custom, widget) in self._extra_widgets.items():
            if isinstance(widget, QComboBox):
                values[field_id] = widget.currentData() or ""
            else:
                values[field_id] = widget.text()
        return values

    # --- load / read ------------------------------------------------------------------------

    def load(self, account: Account, select_game: bool = True) -> None:
        """Fill every field from ``account``. With ``select_game=False`` the game stays on
        the "Choose a game..." placeholder and rank/region wait for a choice."""
        self._base_game_id = account.game_id
        self._base_extra = dict(account.extra)
        self._base_rank, self._base_region = account.rank, account.region
        self.game.blockSignals(True)
        self.game.setCurrentIndex(max(self.game.findData(account.game_id), 0) if select_game
                                  else 0)
        self.game.blockSignals(False)
        self._apply_template(keep_extra=dict(account.extra), account=account)
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

    def _passthrough_extra(self) -> dict[str, str]:
        """Stored values for fields the current game doesn't define (same game only)."""
        if self.game.currentData() != self._base_game_id:
            return {}
        return {k: v for k, v in self._base_extra.items() if k not in self._extra_widgets}

    def dropped_extra_count(self) -> int:
        """How many stored extra values would be dropped by moving to the selected game."""
        if not self.has_game or self.game.currentData() == self._base_game_id:
            return 0
        return sum(1 for k, v in self._base_extra.items() if v and k not in self._extra_widgets)

    def to_account(self, base: Account) -> Account:
        """``base`` with the form's values (raw; core validates and normalizes)."""
        extra = {**self._passthrough_extra(), **self._extra_values()}
        return replace(
            base,
            game_id=self.game.currentData() or "",  # "" = no game chosen yet
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
            extra=tuple(sorted((k, v) for k, v in extra.items() if v)),
        )

    def game_name(self, game_id: str) -> str:
        """Display name of a game (for messages)."""
        game = self._games.get(game_id)
        return game.name if game else ""
