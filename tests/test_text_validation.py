"""Generic text helpers: limits, control/bidi characters, secrets untouched, email, URL."""

from __future__ import annotations

import pytest

from vaultkeeper.config import constants as c
from vaultkeeper.core import text_validation as t
from vaultkeeper.errors import ValidationError

# --- Text -------------------------------------------------------------------------------------


def test_clean_text_strips_and_normalizes() -> None:
    assert t.clean_text("  Cafe\u0301  ", "f", 20) == "Caf\u00e9"


@pytest.mark.parametrize("bad", ["a\x00b", "a\x1bb", "a\nb", "a\u202eb", "\ufeffab", "a\x7fb"])
def test_clean_text_rejects_control_and_bidi(bad: str) -> None:
    with pytest.raises(ValidationError):
        t.clean_text(bad, "f", 50)


def test_multiline_allows_newlines_and_normalizes_crlf() -> None:
    assert t.clean_text("line1\r\nline2\tx", "notes", 50, multiline=True) == "line1\nline2\tx"


def test_length_limit_and_required() -> None:
    with pytest.raises(ValidationError):
        t.clean_text("x" * 11, "f", 10)
    with pytest.raises(ValidationError):
        t.clean_text("   ", "f", 10, required=True)
    with pytest.raises(ValidationError):
        t.clean_text(123, "f", 10)


def test_error_message_never_contains_value() -> None:
    secret_looking = "Fake-Secret\x00Value"
    with pytest.raises(ValidationError) as info:
        t.clean_secret(secret_looking, "password")
    assert "Fake-Secret" not in str(info.value)
    assert info.value.field == "password"


def test_emoji_names_allowed() -> None:
    # Zero-width joiner (category Cf) is used inside emoji and must not be rejected.
    assert t.clean_text("Pro\U0001f469\u200d\U0001f4bb", "display_name", 64)


# --- Secrets ----------------------------------------------------------------------------------


def test_secret_is_not_stripped_or_normalized() -> None:
    raw = "  Cafe\u0301 pass "
    assert t.clean_secret(raw, "password") == raw


@pytest.mark.parametrize("bad", ["pa\nss", "pa\x00ss", "pa\u202ess"])
def test_secret_rejects_controls(bad: str) -> None:
    with pytest.raises(ValidationError):
        t.clean_secret(bad, "password")


def test_secret_length_limit() -> None:
    t.clean_secret("x" * c.MAX_SECRET, "password")
    with pytest.raises(ValidationError):
        t.clean_secret("x" * (c.MAX_SECRET + 1), "password")


def test_optional_secret_empty_is_none() -> None:
    assert t.clean_optional_secret("", "email_password") is None
    assert t.clean_optional_secret(None, "email_password") is None


# --- Fields -----------------------------------------------------------------------------------


@pytest.mark.parametrize("good", ["a@example.test", "first.last+alt@mail.example.com"])
def test_email_valid(good: str) -> None:
    assert t.clean_email(f" {good} ", "email") == good


@pytest.mark.parametrize("bad", ["no-at-sign", "a@b", "a@@example.test", "a b@example.test"])
def test_email_invalid(bad: str) -> None:
    with pytest.raises(ValidationError):
        t.clean_email(bad, "email")


def test_url_rules() -> None:
    assert t.clean_url("https://mail.example.test/login", "u") == "https://mail.example.test/login"
    assert t.clean_url("", "u") is None
    for bad in ("javascript:alert(1)", "file:///C:/x", "ftp://example.test", "https://",
                "https://exa mple.test", "mail.example.test"):
        with pytest.raises(ValidationError):
            t.clean_url(bad, "u")
