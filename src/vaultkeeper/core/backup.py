"""Rotating backups of the (already encrypted) vault file to a user-chosen folder.

A backup is a byte-for-byte copy of the encrypted vault, so it opens with the same master
password and never contains plaintext. Policy (approved):
- after a save, at most one backup per ``min_interval_minutes``;
- on lock / exit if anything changed since the last backup;
- "Backup now" at any time;
- right after a master-password change (older backups still open with the OLD password;
  ``backups_with_old_password`` finds them by their header salt so the user can delete them);
- keep the newest ``keep`` backups of this vault, delete older ones.

The last success and failure times (UTC ISO-8601) are kept so the UI can warn until a backup
works again. Failures are logged by error type only (no paths).
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from vaultkeeper.config.constants import VAULT_EXTENSION
from vaultkeeper.crypto import header
from vaultkeeper.errors import ValidationError, VaultIOError, VaultKeeperError
from vaultkeeper.storage.vault_file import copy_file_verified, read_vault_bytes

log = logging.getLogger(__name__)

_STAMP = "%Y%m%d-%H%M%S"


class BackupService:
    """Owns backup timing and rotation for one vault file."""

    def __init__(
        self,
        vault_path: Path,
        backup_dir: Path | None,
        keep: int,
        min_interval_minutes: int,
        clock: Callable[[], float] = time.time,
        stamp: Callable[[], str] = lambda: time.strftime(_STAMP),
        last_success: str | None = None,
        last_failure: str | None = None,
    ) -> None:
        self._vault = vault_path
        self._clock = clock
        self._stamp = stamp
        self.backup_dir = backup_dir
        self.keep = keep
        self.min_interval_minutes = min_interval_minutes
        self.dirty = False
        self._last_backup_at: float | None = None
        self.last_success = last_success  # UTC ISO-8601 of the last good backup
        self.last_failure = last_failure  # set until a backup succeeds again

    # --- configuration ----------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Backups need a folder."""
        return self.backup_dir is not None

    def configure(self, backup_dir: Path | None, keep: int, min_interval_minutes: int) -> None:
        """Apply new settings. The folder must be an absolute path (ValidationError)."""
        if backup_dir is not None and not backup_dir.is_absolute():
            raise ValidationError("backup_dir",
                                  "must be a full path, including the drive or folder")
        self.backup_dir, self.keep, self.min_interval_minutes = (
            backup_dir, keep, min_interval_minutes)

    def same_folder_as_vault(self) -> bool:
        """True if backups would land next to the vault (no protection if that disk dies)."""
        if self.backup_dir is None:
            return False
        try:
            return self.backup_dir.resolve() == self._vault.parent.resolve()
        except OSError:
            return False

    # --- naming -----------------------------------------------------------------------------

    def _pattern(self) -> re.Pattern[str]:
        return re.compile(rf"^{re.escape(self._vault.stem)}-backup-(\d{{8}}-\d{{6}})(?:-(\d+))?"
                          rf"{re.escape(VAULT_EXTENSION)}$")

    def _order(self, path: Path) -> tuple[str, int]:
        """(timestamp, counter) of one of this vault's backups. The first of a second is 1.

        File names don't sort correctly ("-10" before "-2", "-2" before the first), so
        rotation must never rely on name order.
        """
        match = self._pattern().match(path.name)
        assert match is not None  # noqa: S101 - only called for listed backups
        return match.group(1), int(match.group(2) or 1)

    def list_backups(self) -> list[Path]:
        """This vault's backups in the folder, oldest first (by timestamp, then counter).

        A folder that can't be read raises VaultIOError (never a raw OSError).
        """
        if self.backup_dir is None:
            return []
        pattern = self._pattern()
        try:
            if not self.backup_dir.is_dir():
                return []
            names = [p for p in self.backup_dir.iterdir() if pattern.match(p.name)]
        except OSError:
            raise VaultIOError("Could not read the backup folder.") from None
        return sorted(names, key=self._order)

    def _target(self) -> Path:
        """A new name that sorts after every existing backup made in the same second."""
        assert self.backup_dir is not None  # noqa: S101 - checked by callers
        stamp = self._stamp()
        base = f"{self._vault.stem}-backup-{stamp}"
        same_second = [n for s, n in map(self._order, self.list_backups()) if s == stamp]
        counter = max(same_second, default=0) + 1
        while True:
            suffix = "" if counter == 1 else f"-{counter}"
            target = self.backup_dir / f"{base}{suffix}{VAULT_EXTENSION}"
            if not target.exists():
                return target
            counter += 1

    # --- actions ----------------------------------------------------------------------------

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=UTC).isoformat(timespec="seconds")

    def backup_now(self) -> Path:
        """Write a backup immediately and rotate. Returns the new backup's path.

        A failure is recorded in ``last_failure`` (until a backup succeeds) and re-raised as
        a VaultKeeperError.
        """
        if self.backup_dir is None:
            raise VaultIOError("Choose a backup folder first.")
        if not self._vault.is_file():
            raise VaultIOError("There is no saved vault to back up yet.")
        try:
            target = self._target()
            copy_file_verified(self._vault, target)
            self._last_backup_at = self._clock()
            self.dirty = False
            self._rotate()
        except (VaultKeeperError, OSError) as exc:
            self.last_failure = self._now_iso()
            log.warning("Backup failed (%s)", type(exc).__name__)
            if isinstance(exc, OSError):
                raise VaultIOError("Could not write to the backup folder.") from exc
            raise
        self.last_success, self.last_failure = self._now_iso(), None
        log.info("Backup written")
        return target

    def after_save(self) -> Path | None:
        """Called after every save: back up if the minimum interval has passed."""
        self.dirty = True
        if not self.enabled:
            return None
        interval = self.min_interval_minutes * 60
        if self._last_backup_at is not None and self._clock() - self._last_backup_at < interval:
            return None
        return self.backup_now()

    def on_lock_or_exit(self) -> Path | None:
        """Called on lock and on exit: back up if anything changed since the last backup."""
        if self.enabled and self.dirty:
            return self.backup_now()
        return None

    def after_password_change(self) -> Path | None:
        """Back up at once (ignoring the interval) so a backup with the new password exists."""
        return self.backup_now() if self.enabled else None

    def _salt(self, path: Path) -> bytes | None:
        try:
            return header.unpack(read_vault_bytes(path))[0].salt
        except VaultKeeperError:
            return None  # unreadable or not a vault: never classified, never offered

    def backups_with_old_password(self) -> list[Path]:
        """Backups made before a master-password change (oldest first).

        Every password change uses a fresh salt, so a backup whose header salt differs from
        the vault's opens with an older password. Unreadable files are left out.
        """
        current = self._salt(self._vault)
        if current is None:
            return []
        return [p for p in self.list_backups() if self._salt(p) not in (None, current)]

    def has_backup_with_current_password(self) -> bool:
        """Whether at least one backup opens with the current master password."""
        current = self._salt(self._vault)
        return current is not None and any(self._salt(p) == current
                                           for p in self.list_backups())

    def delete_backups(self, paths: list[Path]) -> int:
        """Delete the given files if they are this vault's backups. Returns how many."""
        ours = set(self.list_backups())
        deleted = 0
        for path in paths:
            if path in ours:
                try:
                    path.unlink()
                except OSError as exc:
                    log.warning("Could not delete an old backup (%s)", type(exc).__name__)
                    continue
                deleted += 1
        log.info("Deleted %d old-password backup(s)", deleted)
        return deleted

    def _rotate(self) -> None:
        backups = self.list_backups()
        for old in backups[: max(len(backups) - self.keep, 0)]:
            with contextlib.suppress(OSError):
                old.unlink()
