"""Header pack/unpack, layout offsets and every bounds/version check."""

from __future__ import annotations

import struct

import pytest

from conftest import FAST_KDF
from vaultkeeper.crypto import header as h
from vaultkeeper.crypto.header import FileKind, VaultHeader
from vaultkeeper.errors import VaultFormatError

SALT = bytes(range(16))
NONCE = bytes(range(100, 112))


def _file(ct_len: int = 20, **overrides: object) -> bytes:
    hdr = VaultHeader(FileKind.VAULT, FAST_KDF, SALT, NONCE, ct_len)
    raw = bytearray(hdr.pack() + b"\xaa" * ct_len)
    offsets = {"version": (8, ">H"), "kind": (10, ">B"), "kdf_id": (11, ">B"),
               "t": (12, ">I"), "m": (16, ">I"), "p": (20, ">B"), "salt_len": (21, ">B"),
               "cipher_id": (38, ">B"), "nonce_len": (39, ">B"), "ct_len_field": (52, ">I")}
    for name, value in overrides.items():
        if name == "magic":
            raw[0:8] = value  # type: ignore[assignment]
            continue
        offset, fmt = offsets[name]
        struct.pack_into(fmt, raw, offset, value)
    return bytes(raw)


def test_header_is_56_bytes_with_documented_layout() -> None:
    raw = _file()
    assert h.HEADER_LEN == 56
    assert raw[0:8] == b"VKVAULT\x00"
    assert struct.unpack_from(">H", raw, 8)[0] == 1
    assert raw[10] == 1 and raw[11] == 1
    assert struct.unpack_from(">IIB", raw, 12) == (1, 8192, 1)
    assert raw[21] == 16 and raw[22:38] == SALT
    assert raw[38] == 1 and raw[39] == 12 and raw[40:52] == NONCE
    assert struct.unpack_from(">I", raw, 52)[0] == 20


def test_round_trip() -> None:
    hdr, ct = h.unpack(_file())
    assert hdr.kdf == FAST_KDF and hdr.salt == SALT and hdr.nonce == NONCE
    assert hdr.file_kind is FileKind.VAULT and ct == b"\xaa" * 20


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"magic": b"NOTVAULT"}, "not a VaultKeeper"),
        ({"version": 2}, "newer version"),
        ({"version": 0}, "Unsupported"),
        ({"kind": 3}, "kind"),
        ({"kdf_id": 2}, "algorithm"),
        ({"cipher_id": 2}, "algorithm"),
        ({"salt_len": 32}, "length"),
        ({"nonce_len": 24}, "length"),
        ({"t": 11}, "time cost"),
        ({"t": 0}, "time cost"),
        ({"m": 2 * 1024 * 1024}, "memory"),
        ({"m": 1024}, "memory"),
        ({"p": 0}, "parallelism"),
        ({"p": 255}, "parallelism"),
        ({"ct_len_field": 21}, "truncated"),
        ({"ct_len_field": 19}, "truncated"),
    ],
)
def test_invalid_headers_rejected(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(VaultFormatError, match=match):
        h.unpack(_file(**overrides))


def test_too_short() -> None:
    with pytest.raises(VaultFormatError):
        h.unpack(b"VKVAULT\x00" + b"\x00" * 10)


def test_ciphertext_shorter_than_tag() -> None:
    with pytest.raises(VaultFormatError):
        h.unpack(_file(ct_len=8))


def test_extra_trailing_data() -> None:
    with pytest.raises(VaultFormatError):
        h.unpack(_file() + b"x")


def test_pack_rejects_bad_lengths() -> None:
    with pytest.raises(VaultFormatError):
        VaultHeader(FileKind.VAULT, FAST_KDF, b"short", NONCE, 20).pack()
