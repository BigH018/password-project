"""The vault file on disk versus what the unlocked session expects (helpers for VaultService).

Before every save the service asks :func:`quarantine_target` what to do with the current
main file:
- unchanged since we last read or wrote it (same SHA-256): rotate it into ``.bak`` as usual;
- it no longer decrypts with our key (damaged), or we opened from ``.bak``: copy it aside
  as ``<vault>.damaged-...`` so it never replaces the good ``.bak``;
- it changed but still decrypts: another window or program saved it (SEC-M2). The save is
  refused with VaultConflictError, so neither version is silently lost.

It also remembers the last-saved time per vault, to notice an older copy put back (SEC-M3).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from vaultkeeper.config import constants as c
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


# --- SEC-M3: a vault file that went back in time ---------------------------------------------
# The last ``updated_at`` this PC saw for each vault is kept in settings (timestamps only). A
# vault that opens with an OLDER time may be an old copy or backup put back in its place.

def vault_key(path: Path) -> str:
    """Stable settings key for a vault file (absolute, case-normalized on Windows)."""
    return os.path.normcase(str(path.resolve()))


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def went_back_in_time(last_seen: str | None, updated_at: str) -> bool:
    """True if the vault's last-saved time is older than the one this PC saw before."""
    before, now = _parse(last_seen), _parse(updated_at)
    return before is not None and now is not None and now < before


def remember_saved_at(seen: dict[str, str], path: Path, updated_at: str) -> dict[str, str]:
    """A copy of ``seen`` with ``path``'s time set (most recent last, oldest dropped)."""
    key = vault_key(path)
    updated = {k: v for k, v in seen.items() if k != key}
    updated[key] = updated_at
    return dict(list(updated.items())[-c.MAX_REMEMBERED_VAULTS:])


def shared_folder_risk(path: Path) -> bool:
    """Whether other users of this PC may be able to change files in the vault's folder
    (a warning only; see ``storage.vault_file.folder_may_be_shared``)."""
    return vault_file.folder_may_be_shared(path)
