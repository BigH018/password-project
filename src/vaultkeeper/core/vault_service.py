"""Vault lifecycle: create, unlock, save, lock, change master password.

Threading model: slow work (Argon2) is split into a pure *prepare* step, which touches no
service state and is safe on a worker thread, and a *commit* step, which updates state on
the caller's thread. ``*_async`` methods run the prepare step through an injected
``TaskRunner`` (``InlineTaskRunner`` in tests, a Qt worker thread in the UI). The plain
methods do both steps synchronously.
"""

from __future__ import annotations

import hmac
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from vaultkeeper.core import vault_disk
from vaultkeeper.core.models import VaultData, utc_now_iso
from vaultkeeper.core.password_policy import check_master_password
from vaultkeeper.core.serialization import dumps_payload, loads_payload
from vaultkeeper.core.tasks import InlineTaskRunner, TaskRunner
from vaultkeeper.crypto import envelope
from vaultkeeper.crypto.header import FileKind
from vaultkeeper.crypto.kdf import (
    DEFAULT_KDF_PARAMS,
    KdfParams,
    derive_key,
    is_weaker_than,
    new_salt,
    wipe,
)
from vaultkeeper.errors import (
    VaultAuthError,
    VaultIOError,
    VaultKeeperError,
    VaultLockedError,
)
from vaultkeeper.storage import vault_file

log = logging.getLogger(__name__)

KeyDeriver = Callable[[str, bytes, KdfParams], bytearray]
WRONG_PASSWORD_DELAY_SECONDS = 1.0


@dataclass(slots=True)
class _Session:
    """Everything held only while unlocked."""

    key: bytearray
    salt: bytes
    kdf: KdfParams
    data: VaultData
    from_backup: bool = False
    disk_digest: bytes | None = None  # SHA-256 of the file bytes we last read or wrote


class VaultService:
    """Owns the unlocked vault state. Not thread-safe: call from one thread only."""

    def __init__(
        self,
        path: Path,
        runner: TaskRunner | None = None,
        kdf_params: KdfParams = DEFAULT_KDF_PARAMS,
        kdf: KeyDeriver = derive_key,
        wrong_password_delay: float = WRONG_PASSWORD_DELAY_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._path = path
        self._runner: TaskRunner = runner or InlineTaskRunner()
        self._kdf_params = kdf_params
        self._kdf = kdf
        self._delay = wrong_password_delay
        self._sleep = sleep
        self._session: _Session | None = None
        self._opened_from_backup = False
        self.last_damaged_copy: Path | None = None
        # Called after every successful write (e.g. the backup service). Never get data.
        self.on_saved: list[Callable[[], None]] = []

    # --- state ------------------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Path of the main vault file."""
        return self._path

    @property
    def backup_path(self) -> Path:
        """Path of the previous-version backup next to the vault."""
        return vault_file.backup_path(self._path)

    @property
    def is_unlocked(self) -> bool:
        """True while a key and decrypted data are held."""
        return self._session is not None

    @property
    def data(self) -> VaultData:
        """The decrypted vault data. Raises VaultLockedError when locked."""
        return self._require_session().data

    @property
    def opened_from_backup(self) -> bool:
        """True after unlocking from ``.bak`` until the next successful save."""
        return self._opened_from_backup

    @property
    def kdf_needs_upgrade(self) -> bool:
        """True if the vault's KDF params are below current defaults (fix: change password)."""
        return is_weaker_than(self._require_session().kdf, self._kdf_params)

    def exists(self) -> bool:
        """Whether a vault file exists at ``path``."""
        return self._path.is_file()

    def has_backup(self) -> bool:
        """Whether a ``.bak`` exists. The UI uses this to OFFER it; unlock never falls back."""
        return self.backup_path.is_file()

    def _require_session(self) -> _Session:
        if self._session is None:
            raise VaultLockedError("The vault is locked.")
        return self._session

    # --- prepare steps (pure: safe on a worker thread) --------------------------------------

    def _prepare_create(self, password: str) -> _Session:
        check_master_password(password)
        if self.exists():
            raise VaultIOError("A vault file already exists at this location.")
        salt = new_salt()
        key = self._kdf(password, salt, self._kdf_params)
        return _Session(key, salt, self._kdf_params, VaultData.empty())

    def _prepare_unlock(self, password: str, use_backup: bool) -> _Session:
        source = self.backup_path if use_backup else self._path
        blob = vault_file.read_vault_bytes(source)
        try:
            hdr, key, plaintext = envelope.open_with_password(
                blob, password, FileKind.VAULT, kdf=self._kdf
            )
        except VaultAuthError:
            self._sleep(self._delay)
            raise
        try:
            data = loads_payload(plaintext)
        except BaseException:
            wipe(key)
            raise
        on_disk = None if use_backup else vault_disk.digest(blob)
        return _Session(key, hdr.salt, hdr.kdf, data, from_backup=use_backup, disk_digest=on_disk)

    def _prepare_change(self, current: str, new: str) -> _Session:
        session = self._require_session()
        check_master_password(new)
        candidate = self._kdf(current, session.salt, session.kdf)
        try:
            matches = hmac.compare_digest(bytes(candidate), bytes(session.key))
        finally:
            wipe(candidate)
        if not matches:
            self._sleep(self._delay)
            raise VaultAuthError()
        salt = new_salt()
        key = self._kdf(new, salt, self._kdf_params)
        return _Session(key, salt, self._kdf_params, session.data, disk_digest=session.disk_digest)

    # --- commit steps (caller's thread) -----------------------------------------------------

    def _commit_new(self, session: _Session) -> None:
        self._write(session)
        self._replace_session(session)
        log.info("Vault created")

    def _commit_unlock(self, session: _Session) -> None:
        self._replace_session(session)
        self._opened_from_backup = session.from_backup
        vault_file.cleanup_stale_temp_files(self._path)
        log.info("Vault unlocked")

    def _commit_change(self, session: _Session) -> None:
        try:
            self._write(session)
        except BaseException:
            wipe(session.key)
            raise
        self._replace_session(session)
        log.info("Master password changed")
        self._refresh_backup_copy()

    def _refresh_backup_copy(self) -> None:
        """After a password change ``.bak`` still opens with the OLD password: replace it with
        a copy of the new file (same data). A failure only means the next save does it."""
        try:
            vault_file.copy_file_verified(self._path, self.backup_path)
        except VaultKeeperError as exc:
            log.warning("Could not refresh .bak after password change (%s)", type(exc).__name__)

    def _replace_session(self, session: _Session) -> None:
        old = self._session
        self._session = session
        if old is not None and old.key is not session.key:
            wipe(old.key)

    # --- public synchronous API -------------------------------------------------------------

    def create(self, password: str) -> None:
        """Create a new empty vault protected by ``password`` and leave it unlocked."""
        self._commit_new(self._prepare_create(password))

    def unlock(self, password: str, *, use_backup: bool = False) -> None:
        """Decrypt the vault (or its ``.bak``). Wrong password -> VaultAuthError after a delay.

        Never falls back to ``.bak`` on its own: the caller must pass ``use_backup=True``
        explicitly (the UI only does so after the user accepts an offer). After unlocking from
        the backup, the next save writes to the main vault path.
        """
        self._commit_unlock(self._prepare_unlock(password, use_backup))

    def change_password(self, current: str, new: str) -> None:
        """Re-encrypt with a new password, fresh salt and current default KDF params."""
        self._commit_change(self._prepare_change(current, new))

    def save(self) -> None:
        """Encrypt and atomically write the current data (fresh nonce every time)."""
        session = self._require_session()
        session.data.updated_at = utc_now_iso()
        self._write(session)

    def lock(self) -> None:
        """Wipe the key (best effort) and drop all decrypted data."""
        session, self._session = self._session, None
        self._opened_from_backup = False
        if session is not None:
            wipe(session.key)
            session.data = VaultData()
            log.info("Vault locked")

    # --- public asynchronous API (prepare on runner, commit via callback) -------------------

    def create_async(self, password: str, on_done: Callable[[], None],
                     on_error: Callable[[BaseException], None]) -> None:
        """Like ``create`` but runs the KDF through the task runner."""
        self._submit(lambda: self._prepare_create(password), self._commit_new, on_done, on_error)

    def unlock_async(self, password: str, on_done: Callable[[], None],
                     on_error: Callable[[BaseException], None], *, use_backup: bool = False
                     ) -> None:
        """Like ``unlock`` but runs the KDF through the task runner."""
        self._submit(lambda: self._prepare_unlock(password, use_backup), self._commit_unlock,
                     on_done, on_error)

    def change_password_async(self, current: str, new: str, on_done: Callable[[], None],
                              on_error: Callable[[BaseException], None]) -> None:
        """Like ``change_password`` but runs the KDF through the task runner."""
        self._submit(lambda: self._prepare_change(current, new), self._commit_change,
                     on_done, on_error)

    def _submit(self, prepare: Callable[[], _Session], commit: Callable[[_Session], None],
                on_done: Callable[[], None], on_error: Callable[[BaseException], None]) -> None:
        def _on_success(session: _Session) -> None:
            try:
                commit(session)
            except Exception as exc:  # delivered to the caller
                on_error(exc)
                return
            on_done()

        self._runner.submit(prepare, _on_success, on_error)

    # --- writing ----------------------------------------------------------------------------

    def _write(self, session: _Session) -> None:
        """Seal and write after checking the file on disk (``core/vault_disk.py``): a damaged
        main file is copied aside instead of over the good ``.bak``, and a file changed by
        another writer is never overwritten (VaultConflictError). A failed write is retried
        by the next save."""
        blob = envelope.seal(dumps_payload(session.data), session.key, session.kdf, session.salt)
        current = self._session  # during a password change: the old session, as on disk
        quarantine = None
        if current is not None:
            quarantine = vault_disk.quarantine_target(
                self._path, current.key, current.disk_digest, self._opened_from_backup)
        vault_file.write_vault_atomic(
            self._path, blob, vault_disk.verifier(session.key), quarantine_as=quarantine
        )
        session.disk_digest = vault_disk.digest(blob)
        if quarantine is not None:
            self.last_damaged_copy = quarantine
            log.warning("Damaged vault file kept aside; backup left untouched")
        self._opened_from_backup = False
        for listener in list(self.on_saved):
            try:
                listener()
            except Exception:  # a listener must never break saving
                log.exception("Save listener failed")
