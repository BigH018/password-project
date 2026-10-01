"""Encrypted export: the whole vault, sealed with its own (separate) password.

The export uses the vault file format with ``file_kind = EXPORT``, so it never contains
plaintext and ``scripts/recover_vault.py`` can read it. Exports always use the ``.vault``
extension (covered by .gitignore).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from vaultkeeper.config.constants import VAULT_EXTENSION
from vaultkeeper.core.password_policy import check_master_password
from vaultkeeper.core.serialization import loads_payload
from vaultkeeper.crypto import envelope
from vaultkeeper.crypto.header import FileKind
from vaultkeeper.crypto.kdf import DEFAULT_KDF_PARAMS, KdfParams, derive_key, new_salt, wipe
from vaultkeeper.errors import ValidationError
from vaultkeeper.storage.vault_file import write_bytes_atomic

log = logging.getLogger(__name__)
KeyDeriver = Callable[[str, bytes, KdfParams], bytearray]


def check_export_path(path: Path, vault_path: Path, overwrite: bool = False) -> Path:
    """Normalize and check an export target. Adds ``.vault`` if missing."""
    if path.suffix.lower() != VAULT_EXTENSION:
        path = path.with_name(path.name + VAULT_EXTENSION)
    # Exports always end in .vault, so the only possible clash is the vault file itself.
    if path.resolve() == vault_path.resolve():
        raise ValidationError("export_file", "can't be the vault file itself")
    if path.exists() and not overwrite:
        raise ValidationError("export_file", "already exists")
    return path


def write_export(
    payload: bytes,
    path: Path,
    password: str,
    kdf_params: KdfParams = DEFAULT_KDF_PARAMS,
    kdf: KeyDeriver = derive_key,
    cancelled: Callable[[], bool] = lambda: False,
) -> bool:
    """Seal ``payload`` (vault JSON bytes) with ``password`` and write it atomically.

    Slow (Argon2): call it through the task runner. The written file is decrypted and parsed
    before it replaces anything. If ``cancelled()`` is true once the key is derived, nothing
    is written and False is returned.
    """
    check_master_password(password)
    salt = new_salt()
    key = kdf(password, salt, kdf_params)
    try:
        if cancelled():
            return False
        blob = envelope.seal(payload, key, kdf_params, salt, FileKind.EXPORT)

        def verify(written: bytes) -> None:
            loads_payload(envelope.open_with_key(written, key, FileKind.EXPORT)[1])

        write_bytes_atomic(path, blob, verify)
    finally:
        wipe(key)
    log.info("Encrypted export written")
    return True
