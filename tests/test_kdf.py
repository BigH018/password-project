"""Argon2id derivation: determinism, sensitivity, bounds, NFC, wiping."""

from __future__ import annotations

import pytest

from conftest import FAST_KDF
from vaultkeeper.crypto import kdf
from vaultkeeper.crypto.kdf import DEFAULT_KDF_PARAMS, KdfParams
from vaultkeeper.errors import VaultFormatError

SALT = bytes(range(16))


def test_deterministic_and_correct_length() -> None:
    a = kdf.derive_key("fake passphrase", SALT, FAST_KDF)
    b = kdf.derive_key("fake passphrase", SALT, FAST_KDF)
    assert isinstance(a, bytearray) and len(a) == kdf.KEY_LEN
    assert a == b


def test_password_salt_and_params_change_key() -> None:
    base = kdf.derive_key("fake passphrase", SALT, FAST_KDF)
    assert kdf.derive_key("fake passphrasE", SALT, FAST_KDF) != base
    assert kdf.derive_key("fake passphrase", bytes(16), FAST_KDF) != base
    assert kdf.derive_key("fake passphrase", SALT, KdfParams(2, 8192, 1)) != base


def test_nfc_normalization_makes_forms_equivalent() -> None:
    composed = "caf\u00e9 fake passphrase"
    decomposed = "cafe\u0301 fake passphrase"
    assert kdf.derive_key(composed, SALT, FAST_KDF) == kdf.derive_key(decomposed, SALT, FAST_KDF)


def test_new_salt_is_random() -> None:
    salts = {kdf.new_salt() for _ in range(50)}
    assert len(salts) == 50 and all(len(s) == kdf.SALT_LEN for s in salts)


@pytest.mark.parametrize(
    "params",
    [
        KdfParams(0, 8192, 1), KdfParams(11, 8192, 1), KdfParams(1, 8191, 1),
        KdfParams(1, 1024 * 1024 + 1, 1), KdfParams(1, 8192, 0), KdfParams(1, 8192, 17),
        KdfParams(True, 8192, 1),  # type: ignore[arg-type]
    ],
)  # fmt: skip
def test_out_of_bounds_params_rejected(params: KdfParams) -> None:
    with pytest.raises(VaultFormatError):
        kdf.check_params(params)
    with pytest.raises(VaultFormatError):
        kdf.derive_key("x", SALT, params)


def test_bounds_edges_accepted() -> None:
    kdf.check_params(KdfParams(1, 8192, 1))
    kdf.check_params(KdfParams(10, 1024 * 1024, 16))
    kdf.check_params(DEFAULT_KDF_PARAMS)


def test_defaults_are_documented_values() -> None:
    assert DEFAULT_KDF_PARAMS == KdfParams(4, 524288, 4)


def test_wrong_salt_length() -> None:
    with pytest.raises(VaultFormatError):
        kdf.derive_key("x", b"short", FAST_KDF)


def test_wipe_zeroes_buffer() -> None:
    key = kdf.derive_key("fake passphrase", SALT, FAST_KDF)
    kdf.wipe(key)
    assert key == bytearray(kdf.KEY_LEN)
    kdf.wipe(None)


def test_is_weaker_than() -> None:
    assert kdf.is_weaker_than(FAST_KDF)
    assert not kdf.is_weaker_than(DEFAULT_KDF_PARAMS)


@pytest.mark.slow
def test_production_params_derive() -> None:
    assert len(kdf.derive_key("fake passphrase", SALT, DEFAULT_KDF_PARAMS)) == kdf.KEY_LEN


# --- SEC-Low4/5: library failures become our errors, never echoing the password ------------


def test_argon2_failure_becomes_a_friendly_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from argon2.exceptions import HashingError

    from vaultkeeper.errors import KeyDerivationError

    def low_memory(**_kw: object) -> bytes:
        raise HashingError("Memory allocation error")

    monkeypatch.setattr(kdf, "hash_secret_raw", low_memory)
    with pytest.raises(KeyDerivationError) as info:
        kdf.derive_key("Fake-Passw0rd-1!", b"s" * 16, FAST_KDF)
    assert "memory" in str(info.value).lower()
    assert "allocation" not in str(info.value)  # the library message isn't passed on
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_lone_surrogate_is_a_wrong_password_without_echo() -> None:
    from vaultkeeper.errors import VaultAuthError

    lone = chr(0xD800)
    with pytest.raises(VaultAuthError) as info:
        kdf.derive_key(f"Fake{lone}pass", b"s" * 16, FAST_KDF)
    assert lone not in str(info.value) and "surrogate" not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__
