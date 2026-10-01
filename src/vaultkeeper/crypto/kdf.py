"""Argon2id key derivation (argon2-cffi low-level API) and parameter bounds.

See docs/VAULT_FORMAT.md for the defaults and why they were chosen.
"""

from __future__ import annotations

import secrets
import unicodedata
from dataclasses import dataclass

from argon2.exceptions import HashingError
from argon2.low_level import Type, hash_secret_raw

from vaultkeeper.errors import KeyDerivationError, VaultAuthError, VaultFormatError

KEY_LEN = 32
SALT_LEN = 16

TIME_COST_RANGE = (1, 10)
MEMORY_KIB_RANGE = (8 * 1024, 1024 * 1024)  # 8 MiB .. 1 GiB
PARALLELISM_RANGE = (1, 16)


@dataclass(frozen=True, slots=True)
class KdfParams:
    """Argon2id cost parameters (stored in the vault header)."""

    time_cost: int
    memory_kib: int
    parallelism: int


# Chosen so unlock stays under ~1 s on a modest PC (~0.3 s on the dev PC, 2026-10-01).
# The 1 GiB / t=10 bounds leave room to raise these later.
DEFAULT_KDF_PARAMS = KdfParams(time_cost=4, memory_kib=512 * 1024, parallelism=4)


def check_params(params: KdfParams) -> KdfParams:
    """Raise VaultFormatError unless every parameter is within bounds.

    Called on header values BEFORE deriving, so a tampered header can't force a huge or
    endless computation.
    """
    for value, (low, high), name in (
        (params.time_cost, TIME_COST_RANGE, "time cost"),
        (params.memory_kib, MEMORY_KIB_RANGE, "memory"),
        (params.parallelism, PARALLELISM_RANGE, "parallelism"),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise VaultFormatError(f"Vault key-derivation {name} is out of range.")
    return params


def is_weaker_than(params: KdfParams, reference: KdfParams = DEFAULT_KDF_PARAMS) -> bool:
    """True if any cost parameter is below ``reference`` (an upgrade is recommended)."""
    return params.time_cost < reference.time_cost or params.memory_kib < reference.memory_kib


def new_salt() -> bytes:
    """Return a fresh random salt."""
    return secrets.token_bytes(SALT_LEN)


def encode_password(password: str) -> bytes:
    """Normalize to NFC and encode as UTF-8.

    The same visible password can arrive in different Unicode forms depending on keyboard
    or IME. NFC makes it derive the same key every time. A string that can't be UTF-8
    (a lone surrogate) can't be anyone's password: it is reported as a wrong password,
    without echoing the character.
    """
    try:
        return unicodedata.normalize("NFC", password).encode("utf-8")
    except UnicodeEncodeError:
        raise VaultAuthError() from None


def derive_key(password: str, salt: bytes, params: KdfParams) -> bytearray:
    """Derive a 32-byte key with Argon2id. Returns a bytearray so callers can wipe it."""
    check_params(params)
    if len(salt) != SALT_LEN:
        raise VaultFormatError("Vault salt has the wrong length.")
    secret = encode_password(password)
    try:
        raw = hash_secret_raw(
            secret=secret,
            salt=salt,
            time_cost=params.time_cost,
            memory_cost=params.memory_kib,
            parallelism=params.parallelism,
            hash_len=KEY_LEN,
            type=Type.ID,
        )
    except HashingError:
        raise KeyDerivationError() from None
    return bytearray(raw)


def wipe(buffer: bytearray | None) -> None:
    """Overwrite a key buffer with zeros (best effort; Python may hold other copies)."""
    if buffer is not None:
        for i in range(len(buffer)):
            buffer[i] = 0
