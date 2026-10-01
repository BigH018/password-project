"""Vault header (format v1): dataclass, pack/unpack, version and bounds checks.

Layout is specified in docs/VAULT_FORMAT.md. All integers are big-endian.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

from vaultkeeper.crypto.cipher import NONCE_LEN, TAG_LEN
from vaultkeeper.crypto.kdf import SALT_LEN, KdfParams, check_params
from vaultkeeper.errors import VaultFormatError

MAGIC = b"VKVAULT\x00"
FORMAT_VERSION = 1
KDF_ARGON2ID = 1
CIPHER_AES256_GCM = 1

# magic, version, kind, kdf_id, t, m, p, salt_len, salt, cipher_id, nonce_len, nonce, ct_len
_STRUCT = struct.Struct(">8sHBBIIBB16sBB12sI")
HEADER_LEN = _STRUCT.size  # 56


class FileKind(IntEnum):
    """What a file holds. Exports use the same format with their own password."""

    VAULT = 1
    EXPORT = 2


@dataclass(frozen=True, slots=True)
class VaultHeader:
    """Parsed header fields. ``pack()`` output is the AEAD associated data."""

    file_kind: FileKind
    kdf: KdfParams
    salt: bytes
    nonce: bytes
    ciphertext_len: int
    format_version: int = FORMAT_VERSION

    def pack(self) -> bytes:
        """Serialize to exactly HEADER_LEN bytes."""
        if len(self.salt) != SALT_LEN or len(self.nonce) != NONCE_LEN:
            raise VaultFormatError("Vault header has a wrong salt or nonce length.")
        return _STRUCT.pack(
            MAGIC, self.format_version, int(self.file_kind), KDF_ARGON2ID,
            self.kdf.time_cost, self.kdf.memory_kib, self.kdf.parallelism,
            SALT_LEN, self.salt, CIPHER_AES256_GCM, NONCE_LEN, self.nonce,
            self.ciphertext_len,
        )  # fmt: skip


def unpack(data: bytes) -> tuple[VaultHeader, bytes]:
    """Parse and bounds-check the header. Returns ``(header, ciphertext)``.

    Every check runs before any key derivation. Errors are VaultFormatError, which is safe
    to report because it reveals nothing about the password.
    """
    if len(data) < HEADER_LEN:
        raise VaultFormatError("File is too short to be a vault.")
    (magic, version, kind, kdf_id, t_cost, m_kib, par, salt_len, salt, cipher_id, nonce_len,
     nonce, ct_len) = _STRUCT.unpack_from(data)  # fmt: skip
    if magic != MAGIC:
        raise VaultFormatError("File is not a VaultKeeper vault.")
    if version > FORMAT_VERSION:
        raise VaultFormatError("This vault was created by a newer version of VaultKeeper.")
    if version != FORMAT_VERSION:
        raise VaultFormatError("Unsupported vault format version.")
    try:
        file_kind = FileKind(kind)
    except ValueError:
        raise VaultFormatError("Unknown vault file kind.") from None
    if kdf_id != KDF_ARGON2ID or cipher_id != CIPHER_AES256_GCM:
        raise VaultFormatError("Unsupported vault algorithm.")
    if salt_len != SALT_LEN or nonce_len != NONCE_LEN:
        raise VaultFormatError("Vault header has a wrong salt or nonce length.")
    kdf = check_params(KdfParams(t_cost, m_kib, par))
    ciphertext = data[HEADER_LEN:]
    if ct_len < TAG_LEN or ct_len != len(ciphertext):
        raise VaultFormatError("Vault file is truncated or has extra data.")
    header = VaultHeader(file_kind, kdf, salt, nonce, ct_len, version)
    return header, ciphertext
