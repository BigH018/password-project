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
from typing import Protocol, TypeVar

from vaultkeeper.core.models import VaultData, utc_now_iso
from vaultkeeper.core.password_policy import check_master_password
from vaultkeeper.core.serialization import dumps_payload, loads_payload
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
from vaultkeeper.errors import VaultAuthError, VaultIOError, VaultLockedError
from vaultkeeper.storage import vault_file

log = logging.getLogger(__name__)

T = TypeVar("T")
KeyDeriver = Callable[[str, bytes, KdfParams], bytearray]
WRONG_PASSWORD_DELAY_SECONDS = 1.0


class TaskRunner(Protocol):
    """Runs ``task`` (possibly on another thread) and delivers the result via callbacks.

    Callbacks must be invoked on the thread that owns the service (the UI thread).
    """

    def submit(
        self,
        task: Callable[[], T],
        on_success: Callable[[T], None],
        on_error: Callable[[BaseException], None],
    ) -> None: ...


class InlineTaskRunner:
    """Runs tasks immediately on the calling thread (tests, scripts)."""

    def submit(
        self,
        task: Callable[[], T],
        on_success: Callable[[T], None],
        on_error: Callable[[BaseException], None],
    ) -> None:
        try:
            result = task()
        except Exception as exc:  # every failure is delivered to the caller
            on_error(exc)
            return
        on_success(result)


@dataclass(slots=True)
class _Session:
    """Everything held only while unlocked."""

    key: bytearray
    salt: bytes
    kdf: KdfParams
    data: VaultData


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
        return _Session(key, hdr.salt, hdr.kdf, data)

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
        return _Session(key, salt, self._kdf_params, session.data)

    # --- commit steps (caller's thread) -----------------------------------------------------

    def _commit_new(self, session: _Session) -> None:
        self._write(session)
        self._replace_session(session)
        log.info("Vault created")

    def _commit_unlock(self, session: _Session) -> None:
        self._replace_session(session)
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
        blob = envelope.seal(dumps_payload(session.data), session.key, session.kdf, session.salt)
        vault_file.write_vault_atomic(self._path, blob, self._verifier(session.key))

    @staticmethod
    def _verifier(key: bytearray) -> Callable[[bytes], None]:
        def verify(written: bytes) -> None:
            _hdr, plaintext = envelope.open_with_key(written, key, FileKind.VAULT)
            loads_payload(plaintext)

        return verify

