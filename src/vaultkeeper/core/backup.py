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

Threading (CR-L6), like ``VaultService``: ``prepare*`` reads the encrypted vault on the
caller's (UI) thread, which is fast and never holds the vault file open during a save;
``run_backup_job`` does the slow part (list, write, verify, rotate in the backup folder) and
touches no service state, so it can run on a worker thread; ``finish`` records the result on
the caller's thread. ``backup_now``/``after_save``/``on_lock_or_exit`` do all three at once.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from vaultkeeper.config.constants import VAULT_EXTENSION
from vaultkeeper.crypto import header
from vaultkeeper.errors import ValidationError, VaultFormatError, VaultIOError, VaultKeeperError
from vaultkeeper.storage.vault_file import read_vault_bytes, write_bytes_atomic

log = logging.getLogger(__name__)

_STAMP = "%Y%m%d-%H%M%S"


# --- naming (shared by the service and the worker step) ---------------------------------------


def _pattern(stem: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(stem)}-backup-(\d{{8}}-\d{{6}})(?:-(\d+))?"
                      rf"{re.escape(VAULT_EXTENSION)}$")


def _order(pattern: re.Pattern[str], path: Path) -> tuple[str, int]:
    """(timestamp, counter) of a backup; the first of a second is 1.

    File names don't sort correctly ("-10" before "-2", "-2" before the first), so rotation
    must never rely on name order.
    """
    match = pattern.match(path.name)
    assert match is not None  # noqa: S101 - only called for listed backups
    return match.group(1), int(match.group(2) or 1)


def list_backup_files(folder: Path | None, stem: str) -> list[Path]:
    """A vault's backups in ``folder``, oldest first. VaultIOError if it can't be read."""
    if folder is None:
        return []
    pattern = _pattern(stem)
    try:
        if not folder.is_dir():
            return []
        names = [p for p in folder.iterdir() if pattern.match(p.name)]
    except OSError:
        raise VaultIOError("Could not read the backup folder.") from None
    return sorted(names, key=lambda p: _order(pattern, p))


@dataclass(frozen=True, slots=True)
class BackupJob:
    """One backup: the encrypted vault bytes (read on the caller's thread) and where to."""

    data: bytes = field(repr=False)
    folder: Path
    stem: str
    stamp: str
    keep: int
    previous_backup_at: float | None  # restored if the job fails, so it's retried soon


def _new_target(job: BackupJob) -> Path:
    """A new name that sorts after every existing backup made in the same second."""
    pattern = _pattern(job.stem)
    same_second = [n for s, n in (_order(pattern, p)
                                  for p in list_backup_files(job.folder, job.stem))
                   if s == job.stamp]
    counter = max(same_second, default=0) + 1
    while True:
        suffix = "" if counter == 1 else f"-{counter}"
        target = job.folder / f"{job.stem}-backup-{job.stamp}{suffix}{VAULT_EXTENSION}"
        if not target.exists():
            return target
        counter += 1


def run_backup_job(job: BackupJob) -> Path:
    """The slow part: write and verify the copy, then rotate. Touches no service state, so
    it is safe on a worker thread. Raises VaultKeeperError or OSError on failure."""

    def same_bytes(written: bytes) -> None:
        if written != job.data:
            raise VaultFormatError("Backup copy does not match the vault file.")

    target = _new_target(job)
    write_bytes_atomic(target, job.data, same_bytes)
    backups = list_backup_files(job.folder, job.stem)
    for old in backups[: max(len(backups) - job.keep, 0)]:
        with contextlib.suppress(OSError):
            old.unlink()
    return target


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

    @property
    def vault_path(self) -> Path:
        """The vault this service backs up."""
        return self._vault

    def list_backups(self) -> list[Path]:
        """This vault's backups in the folder, oldest first (by timestamp, then counter).

        A folder that can't be read raises VaultIOError (never a raw OSError).
        """
        return list_backup_files(self.backup_dir, self._vault.stem)

    # --- actions ----------------------------------------------------------------------------

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self._clock(), tz=UTC).isoformat(timespec="seconds")

    def prepare(self) -> BackupJob:
        """Start a backup now: read the encrypted vault (fast, on the caller's thread).

        Raises VaultIOError if there's no folder or no vault; a read failure is recorded.
        """
        if self.backup_dir is None:
            raise VaultIOError("Choose a backup folder first.")
        if not self._vault.is_file():
            raise VaultIOError("There is no saved vault to back up yet.")
        try:
            data = read_vault_bytes(self._vault)
        except VaultKeeperError as exc:
            self._record_failure(exc)
            raise
        job = BackupJob(data, self.backup_dir, self._vault.stem, self._stamp(), self.keep,
                        self._last_backup_at)
        self._last_backup_at, self.dirty = self._clock(), False  # later saves set dirty again
        return job

    def prepare_after_save(self) -> BackupJob | None:
        """After every save: a job if the minimum interval has passed, else None."""
        self.dirty = True
        if not self.enabled:
            return None
        interval = self.min_interval_minutes * 60
        if self._last_backup_at is not None and self._clock() - self._last_backup_at < interval:
            return None
        return self.prepare()

    def prepare_on_lock_or_exit(self) -> BackupJob | None:
        """On lock and exit: a job if anything changed since the last backup, else None."""
        return self.prepare() if self.enabled and self.dirty else None

    def finish(self, job: BackupJob, error: BaseException | None) -> VaultKeeperError | None:
        """Record a job's result (caller's thread). Returns the error to show, if any."""
        if error is None:
            self.last_success, self.last_failure = self._now_iso(), None
            log.info("Backup written")
            return None
        self._last_backup_at, self.dirty = job.previous_backup_at, True  # retry soon
        self._record_failure(error)
        if isinstance(error, VaultKeeperError):
            return error
        return VaultIOError("Could not write to the backup folder.")

    def _record_failure(self, error: BaseException) -> None:
        self.last_failure = self._now_iso()
        log.warning("Backup failed (%s)", type(error).__name__)

    def _run(self, job: BackupJob | None) -> Path | None:
        """Run a job here and now (synchronous use)."""
        if job is None:
            return None
        try:
            target = run_backup_job(job)
        except (VaultKeeperError, OSError) as exc:
            error = self.finish(job, exc)
            assert error is not None  # noqa: S101 - a failure always has an error
            raise error from exc
        self.finish(job, None)
        return target

    def backup_now(self) -> Path:
        """Write a backup immediately and rotate. Returns the new backup's path.

        A failure is recorded in ``last_failure`` (until a backup succeeds) and raised as a
        VaultKeeperError.
        """
        target = self._run(self.prepare())
        assert target is not None  # noqa: S101 - prepare() always returns a job
        return target

    def after_save(self) -> Path | None:
        """Called after every save: back up if the minimum interval has passed."""
        return self._run(self.prepare_after_save())

    def on_lock_or_exit(self) -> Path | None:
        """Called on lock and on exit: back up if anything changed since the last backup."""
        return self._run(self.prepare_on_lock_or_exit())

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
