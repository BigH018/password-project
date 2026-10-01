"""AES-256-GCM authenticated encryption via ``cryptography``'s AESGCM."""

from __future__ import annotations

import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from vaultkeeper.crypto.kdf import KEY_LEN
from vaultkeeper.errors import VaultAuthError, VaultFormatError

NONCE_LEN = 12
TAG_LEN = 16


def new_nonce() -> bytes:
    """Return a fresh random 96-bit nonce. Call this for EVERY encryption."""
    return secrets.token_bytes(NONCE_LEN)


def _aead(key: bytes | bytearray) -> AESGCM:
    if len(key) != KEY_LEN:
        raise VaultFormatError("Encryption key has the wrong length.")
    # AESGCM needs immutable bytes. This copy can't be wiped (documented limitation).
    return AESGCM(bytes(key))


def encrypt(key: bytes | bytearray, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Encrypt and authenticate ``plaintext`` and ``aad``. Returns ciphertext || tag."""
    if len(nonce) != NONCE_LEN:
        raise VaultFormatError("Nonce has the wrong length.")
    return _aead(key).encrypt(nonce, plaintext, aad)


def decrypt(key: bytes | bytearray, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    """Verify and decrypt. Raises VaultAuthError on a wrong key or ANY modification."""
    if len(nonce) != NONCE_LEN:
        raise VaultFormatError("Nonce has the wrong length.")
    try:
        return _aead(key).decrypt(nonce, ciphertext, aad)
    except InvalidTag:
        raise VaultAuthError() from None
