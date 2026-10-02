"""Rank pictures: the PNG check and the base64 text form stored in the vault."""

from __future__ import annotations

import base64
import struct

import pytest

from fake_data import tiny_png
from vaultkeeper.core.rank_image import (
    MAX_BYTES,
    MAX_SIDE,
    image_from_text,
    image_to_text,
    is_valid_rank_image,
)


def _with_size(width: int, height: int) -> bytes:
    """tiny_png with the IHDR width/height overwritten (the check only reads the header)."""
    data = bytearray(tiny_png())
    data[16:24] = struct.pack(">II", width, height)
    return bytes(data)


def test_small_png_is_valid() -> None:
    assert is_valid_rank_image(tiny_png())
    assert is_valid_rank_image(tiny_png(MAX_SIDE, MAX_SIDE))
    assert is_valid_rank_image(tiny_png(1, MAX_SIDE))


@pytest.mark.parametrize("bad", [
    b"",
    b"GIF89a" + bytes(40),                       # another format
    tiny_png()[:20],                             # cut short
    tiny_png()[:12] + b"IDAT" + tiny_png()[16:],  # first chunk not IHDR
    _with_size(MAX_SIDE + 1, 4),
    _with_size(4, MAX_SIDE + 1),
    _with_size(0, 4),
    tiny_png() + bytes(MAX_BYTES),               # too many bytes
    bytearray(tiny_png()),                       # not bytes
    "a string",
    None,
], ids=["empty", "gif", "short", "no-ihdr", "too-wide", "too-tall", "zero-width", "too-big",
        "bytearray", "str", "none"])
def test_invalid_images_rejected(bad: object) -> None:
    assert not is_valid_rank_image(bad)


def test_text_round_trip() -> None:
    data = tiny_png()
    text = image_to_text(data)
    assert text.isascii() and image_from_text(text) == data


@pytest.mark.parametrize("bad", [
    "not base64!",
    "QUJD\n",                                     # whitespace is not accepted
    base64.b64encode(b"GIF89a" + bytes(40)).decode(),  # decodes, but not a PNG
    123,
    None,
])
def test_bad_text_gives_none(bad: object) -> None:
    assert image_from_text(bad) is None
