"""Add / edit account: the form, a live duplicate warning, save, unsaved-changes protection."""

from __future__ import annotations

from PyQt5.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from vaultkeeper.core.account_service import AccountService, DuplicateField
from vaultkeeper.core.models import Account, Game
from vaultkeeper.errors import VaultKeeperError
from vaultkeeper.ui import messages
from vaultkeeper.ui.theme import ERROR_STYLE
from vaultkeeper.ui.widgets.account_form import AccountForm

DUPLICATE_STYLE = "color: #ffcf6e;"


class AccountDialog(QDialog):
    """Accepts after a successful save; ``saved`` holds the stored account."""

    def __init__(
        self,
        accounts: AccountService,
        games: list[Game],
        account: Account | None = None,
        default_game_id: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._accounts = accounts
        self._is_new = account is None
        game_id = default_game_id or (games[0].id if games else "")
        self._base = account if account is not None else accounts.new_draft(game_id)
        self.saved: Account | None = None
        self.setWindowTitle("Add account" if self._is_new else "Edit account")
        self.setMinimumWidth(520)

        self.form = AccountForm(games, self)
        self.form.load(self._base)
        self.duplicate_label = QLabel(self)
        self.duplicate_label.setStyleSheet(DUPLICATE_STYLE)
        self.duplicate_label.setWordWrap(True)
        self.error_label = QLabel(self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.error_label.setWordWrap(True)
        self.save_button = QPushButton("Save", self)
        self.save_button.setDefault(True)
        self.cancel_button = QPushButton("Cancel", self)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.form)
        layout.addWidget(self.duplicate_label)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self._initial = self._snapshot()
        self.form.changed.connect(self._on_changed)
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.reject)
        self._update_duplicates()
        self.form.display_name.setFocus()

    # --- change tracking ----------------------------------------------------------------

    def _snapshot(self) -> Account:
        return self.form.to_account(self._base)

    @property
    def has_changes(self) -> bool:
        """Whether any field differs from when the dialog opened."""
        return self._snapshot() != self._initial

    def _on_changed(self) -> None:
        self.error_label.clear()
        self._update_duplicates()

    def _update_duplicates(self) -> None:
        candidate = self._snapshot()
        matches = self._accounts.find_duplicates(candidate)
        if not matches:
            self.duplicate_label.clear()
            return
        lines = []
        for match in matches[:3]:
            other = self._accounts.get(match.account_id)
            what = "login" if match.field is DuplicateField.LOGIN else "name#tag"
            label = other.riot_id or other.login_username
            lines.append(f"Heads up: {label} in {self.form.game_name(other.game_id)} has the "
                         f"same {what}. You can still save.")
        self.duplicate_label.setText("\n".join(lines))

    # --- saving -------------------------------------------------------------------------

    def _save(self) -> None:
        draft = self._snapshot()
        try:
            stored = self._accounts.add(draft) if self._is_new else self._accounts.update(draft)
        except VaultKeeperError as exc:
            self.error_label.setText(messages.error_text(exc))
            return
        self.saved = stored
        self._initial = self._snapshot()  # nothing unsaved any more
        super().accept()

    # --- closing ------------------------------------------------------------------------

    def reject(self) -> None:
        """Cancel / Esc / window close (Qt routes it here): asks before discarding changes."""
        if self.has_changes and not messages.confirm(
            self, "Discard changes?", "This account has unsaved changes. Discard them?",
            ok_text="Discard",
        ):
            return
        super().reject()

    def force_close(self) -> None:
        """Close without asking (used when the vault locks: drafts are discarded)."""
        super().reject()
