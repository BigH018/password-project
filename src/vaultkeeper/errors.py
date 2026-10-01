"""Exception hierarchy for VaultKeeper.

Rules for every exception raised in this project:
- Messages never contain user data (passwords, usernames, emails, names, notes, paths to
  pasted content, ...). Name the field or operation, never the value.
- Library exceptions are translated at layer boundaries into these classes.

This module is a leaf: it imports nothing from the rest of the package.
"""

from __future__ import annotations


class VaultKeeperError(Exception):
    """Base class for all application errors."""


class VaultFormatError(VaultKeeperError):
    """The vault file or payload is malformed, truncated or an unsupported version."""


class VaultAuthError(VaultKeeperError):
    """Decryption failed: wrong password OR the file was tampered with or damaged.

    The two cases are deliberately indistinguishable.
    """

    def __init__(self) -> None:
        super().__init__("Wrong password or the vault file is damaged.")


class VaultLockedError(VaultKeeperError):
    """An operation needs an unlocked vault."""


class VaultIOError(VaultKeeperError):
    """A filesystem operation on the vault, backup or settings failed."""


class ValidationError(VaultKeeperError):
    """User input failed validation.

    Carries the field name and a generic reason. Never the offending value.
    """

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


class WeakPasswordError(ValidationError):
    """A new master password does not meet the password policy."""

    def __init__(self, reason: str) -> None:
        super().__init__("master_password", reason)


class NotFoundError(VaultKeeperError):
    """A referenced game or account does not exist."""


class DuplicateGameError(VaultKeeperError):
    """A game with the same name (case-insensitive) already exists."""


class GameInUseError(VaultKeeperError):
    """A game cannot be deleted while accounts still reference it."""


class VaultConflictError(VaultKeeperError):
    """The vault file changed on disk since it was loaded (another window or program).

    Saving is refused so neither version is silently lost.
    """

    def __init__(self) -> None:
        super().__init__(
            "The vault file was changed by another program or Account Manager window since "
            "you unlocked it, so nothing was saved. Lock and unlock to load the latest version."
        )
