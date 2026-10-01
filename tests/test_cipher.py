"""AES-256-GCM wrapper: round trip, tamper detection, nonce rules."""

from __future__ import annotations

import pytest

from vaultkeeper.crypto import cipher
from vaultkeeper.errors import VaultAuthError, VaultFormatError

KEY = bytearray(range(32))
AAD = b"header-bytes"


def test_round_trip() -> None:
    nonce = cipher.new_nonce()
    ct = cipher.encrypt(KEY, nonce, b"fake secret payload", AAD)
    assert len(ct) == len(b"fake secret payload") + cipher.TAG_LEN
    assert b"fake secret payload" not in ct
    assert cipher.decrypt(KEY, nonce, ct, AAD) == b"fake secret payload"


def test_wrong_key_fails() -> None:
    nonce = cipher.new_nonce()
    ct = cipher.encrypt(KEY, nonce, b"data", AAD)
    with pytest.raises(VaultAuthError):
        cipher.decrypt(bytes(32), nonce, ct, AAD)


def test_any_bit_flip_in_ciphertext_fails() -> None:
    nonce = cipher.new_nonce()
    ct = cipher.encrypt(KEY, nonce, b"some fake payload", AAD)
    for i in range(len(ct)):
        tampered = bytearray(ct)
        tampered[i] ^= 0x01
        with pytest.raises(VaultAuthError):
            cipher.decrypt(KEY, nonce, bytes(tampered), AAD)


def test_aad_or_nonce_change_fails() -> None:
    nonce = cipher.new_nonce()
    ct = cipher.encrypt(KEY, nonce, b"data", AAD)
    with pytest.raises(VaultAuthError):
        cipher.decrypt(KEY, nonce, ct, AAD + b"x")
    with pytest.raises(VaultAuthError):
        cipher.decrypt(KEY, bytes(12), ct, AAD)


def test_nonces_are_unique() -> None:
    nonces = {cipher.new_nonce() for _ in range(1000)}
    assert len(nonces) == 1000


def test_bad_lengths() -> None:
    with pytest.raises(VaultFormatError):
        cipher.encrypt(b"short", cipher.new_nonce(), b"x", AAD)
    with pytest.raises(VaultFormatError):
        cipher.encrypt(KEY, b"short", b"x", AAD)
    with pytest.raises(VaultFormatError):
        cipher.decrypt(KEY, b"short", b"x" * 32, AAD)
