"""Rank pictures: small PNG images stored with a rank in a game's template (in the vault).

The UI shrinks a picked .ico/.png file to at most ``MAX_SIDE`` pixels each way and encodes
it as PNG. This module only checks the result and converts it to and from the base64 text
kept in the JSON payload. It never decodes pixels (core does not use Qt).
"""

from __future__ import annotations

import base64
import binascii
import struct

PNG_SIGNATURE = bytes((0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A))
MAX_SIDE = 64
MAX_BYTES = 24 * 1024
_IHDR_END = 33  # signature (8) + length (4) + "IHDR" (4) + body (13) + crc (4)


def is_valid_rank_image(data: object) -> bool:
    """True for PNG bytes of at most ``MAX_BYTES`` whose header says 1..MAX_SIDE pixels."""
    if not isinstance(data, bytes) or not _IHDR_END <= len(data) <= MAX_BYTES:
        return False
    if not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return False
    width, height = struct.unpack(">II", data[16:24])
    return 1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE


def image_to_text(data: bytes) -> str:
    """The base64 form stored in the vault payload."""
    return base64.b64encode(data).decode("ascii")


def image_from_text(text: object) -> bytes | None:
    """Decode a stored picture, or None if it isn't strict base64 of a valid rank image."""
    if not isinstance(text, str) or not text.isascii():
        return None
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    return data if is_valid_rank_image(data) else None
