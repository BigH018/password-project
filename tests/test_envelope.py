"""Full seal/open: header is AAD, fresh nonce per seal, KDF only after bounds pass."""

from __future__ import annotations

import struct

import pytest

from conftest import FAST_KDF
from vaultkeeper.crypto import envelope
from vaultkeeper.crypto.header import HEADER_LEN, FileKind
from vaultkeeper.crypto.kdf import derive_key, new_salt
from vaultkeeper.errors import VaultAuthError, VaultFormatError

PASSWORD = "fake envelope passphrase"


@pytest.fixture
def sealed() -> tuple[bytes, bytearray]:
    salt = new_salt()
    key = derive_key(PASSWORD, salt, FAST_KDF)
    return envelope.seal(b'{"fake":"payload"}', key, FAST_KDF, salt), key


def test_open_with_key_and_password(sealed: tuple[bytes, bytearray]) -> None:
    blob, key = sealed
    assert envelope.open_with_key(blob, key)[1] == b'{"fake":"payload"}'
    hdr, derived, plaintext = envelope.open_with_password(blob, PASSWORD)
    assert plaintext == b'{"fake":"payload"}' and derived == key
    assert hdr.file_kind is FileKind.VAULT


def test_wrong_password(sealed: tuple[bytes, bytearray]) -> None:
    with pytest.raises(VaultAuthError):
        envelope.open_with_password(sealed[0], "wrong fake passphrase")


def test_every_byte_flip_detected(sealed: tuple[bytes, bytearray]) -> None:
    blob, key = sealed
    for i in range(len(blob)):
        tampered = bytearray(blob)
        tampered[i] ^= 0x01
        with pytest.raises((VaultAuthError, VaultFormatError)):
            envelope.open_with_key(bytes(tampered), key)


def test_header_kdf_change_detected_via_password(sealed: tuple[bytes, bytearray]) -> None:
    """Changing KDF params in the header (still in bounds) must fail authentication."""
    tampered = bytearray(sealed[0])
    struct.pack_into(">I", tampered, 12, 2)  # time_cost 1 -> 2
    with pytest.raises(VaultAuthError):
        envelope.open_with_password(bytes(tampered), PASSWORD)


def test_fresh_nonce_each_seal() -> None:
    salt = new_salt()
    key = derive_key(PASSWORD, salt, FAST_KDF)
    blobs = [envelope.seal(b"same", key, FAST_KDF, salt) for _ in range(20)]
    nonces = {b[40:52] for b in blobs}
    assert len(nonces) == 20
    assert len({b[HEADER_LEN:] for b in blobs}) == 20


def test_kdf_not_called_when_header_out_of_bounds(sealed: tuple[bytes, bytearray]) -> None:
    tampered = bytearray(sealed[0])
    struct.pack_into(">I", tampered, 16, 4 * 1024 * 1024)  # 4 GiB memory
    calls: list[object] = []

    def spy(*args: object) -> bytearray:
        calls.append(args)
        return bytearray(32)

    with pytest.raises(VaultFormatError):
        envelope.open_with_password(bytes(tampered), PASSWORD, kdf=spy)
    assert calls == []


def test_expected_kind_enforced() -> None:
    salt = new_salt()
    key = derive_key(PASSWORD, salt, FAST_KDF)
    export_blob = envelope.seal(b"x", key, FAST_KDF, salt, FileKind.EXPORT)
    with pytest.raises(VaultFormatError):
        envelope.open_with_key(export_blob, key, FileKind.VAULT)
    with pytest.raises(VaultFormatError):
        envelope.open_with_password(export_blob, PASSWORD, FileKind.VAULT)
    assert envelope.open_with_key(export_blob, key, FileKind.EXPORT)[1] == b"x"


def test_ciphertext_does_not_contain_plaintext(sealed: tuple[bytes, bytearray]) -> None:
    assert b"payload" not in sealed[0]
