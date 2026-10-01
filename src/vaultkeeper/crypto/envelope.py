"""Seal/open a complete vault file: header (used as AAD) + AES-256-GCM ciphertext."""

from __future__ import annotations

from collections.abc import Callable

from vaultkeeper.crypto import cipher, header
from vaultkeeper.crypto.header import FileKind, VaultHeader
from vaultkeeper.crypto.kdf import KdfParams, derive_key, wipe
from vaultkeeper.errors import VaultFormatError

KeyDeriver = Callable[[str, bytes, KdfParams], bytearray]


def seal(
    plaintext: bytes,
    key: bytes | bytearray,
    kdf: KdfParams,
    salt: bytes,
    file_kind: FileKind = FileKind.VAULT,
) -> bytes:
    """Encrypt ``plaintext`` into full file bytes, using a fresh nonce every call."""
    hdr = VaultHeader(
        file_kind=file_kind,
        kdf=kdf,
        salt=salt,
        nonce=cipher.new_nonce(),
        ciphertext_len=len(plaintext) + cipher.TAG_LEN,
    )
    aad = hdr.pack()
    return aad + cipher.encrypt(key, hdr.nonce, plaintext, aad)


def read_header(data: bytes) -> VaultHeader:
    """Parse and bounds-check the header only (no key needed)."""
    return header.unpack(data)[0]


def open_with_key(
    data: bytes, key: bytes | bytearray, expected_kind: FileKind | None = None
) -> tuple[VaultHeader, bytes]:
    """Verify and decrypt file bytes with an already-derived key."""
    hdr, ciphertext = header.unpack(data)
    if expected_kind is not None and hdr.file_kind != expected_kind:
        raise VaultFormatError("File is not the expected kind (vault vs export).")
    plaintext = cipher.decrypt(key, hdr.nonce, ciphertext, data[: header.HEADER_LEN])
    return hdr, plaintext


def open_with_password(
    data: bytes,
    password: str,
    expected_kind: FileKind | None = None,
    kdf: KeyDeriver = derive_key,
) -> tuple[VaultHeader, bytearray, bytes]:
    """Check the header, derive the key from it, then decrypt.

    Returns ``(header, key, plaintext)``. The caller owns ``key`` and must ``wipe`` it.
    """
    hdr = read_header(data)  # bounds checks happen BEFORE the expensive KDF
    if expected_kind is not None and hdr.file_kind != expected_kind:
        raise VaultFormatError("File is not the expected kind (vault vs export).")
    key = kdf(password, hdr.salt, hdr.kdf)
    try:
        _, plaintext = open_with_key(data, key)
    except BaseException:
        wipe(key)
        raise
    return hdr, key, plaintext
