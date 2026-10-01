"""The vault file on disk versus what the unlocked session expects (helpers for VaultService).

Before every save the service asks :func:`quarantine_target` what to do with the current
main file:
- unchanged since we last read or wrote it (same SHA-256): rotate it into ``.bak`` as usual;
- it no longer decrypts with our key (damaged), or we opened from ``.bak``: copy it aside
  as ``<vault>.damaged-...`` so it never replaces the good ``.bak``;
- it changed but still decrypts: another window or program saved it (SEC-M2). The save is
  refused with VaultConflictError, so neither version is silently lost.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Callable
from pathlib import Path

from vaultkeeper.core.serialization import loads_payload
from vaultkeeper.crypto import envelope
from vaultkeeper.crypto.header import FileKind
from vaultkeeper.errors import VaultAuthError, VaultConflictError, VaultFormatError
from vaultkeeper.storage import vault_file

log = logging.getLogger(__name__)


def digest(blob: bytes) -> bytes:
    """Fingerprint of the vault bytes we last read or wrote."""
    return hashlib.sha256(blob).digest()


def verifier(key: bytearray) -> Callable[[bytes], None]:
    """Check that vault bytes decrypt with ``key`` and parse (raises VaultKeeperError)."""

    def verify(written: bytes) -> None:
        _hdr, plaintext = envelope.open_with_key(written, key, FileKind.VAULT)
        loads_payload(plaintext)

    return verify


def quarantine_target(path: Path, key: bytearray, expected: bytes | None,
                      opened_from_backup: bool) -> Path | None:
    """Where to copy the current main file aside before saving, or None to rotate normally.

    ``expected`` is the digest of the bytes this session last read or wrote (None: unknown).
    Raises VaultConflictError if the file changed on disk but still decrypts with ``key``.
    """
    if not path.exists():
        return None
    if opened_from_backup:
        return vault_file.damaged_path(path)
    on_disk = vault_file.read_vault_bytes(path)
    if expected is not None and hmac.compare_digest(digest(on_disk), expected):
        return None
    try:
        verifier(key)(on_disk)
    except (VaultAuthError, VaultFormatError):
        log.warning("Vault file on disk no longer decrypts; keeping it out of .bak")
        return vault_file.damaged_path(path)
    if expected is not None:
        log.warning("Vault file changed on disk since it was loaded; save refused")
        raise VaultConflictError()
    return None
