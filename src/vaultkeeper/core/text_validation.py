"""Generic text validation helpers used by every field rule.

Every ``clean_*`` function returns a normalized value or raises ``ValidationError`` naming the
field and a generic reason. Error messages never include the rejected value.

- Plain text is NFC-normalized and stripped. Control characters (except newline/tab in
  multi-line notes) and bidirectional override characters are rejected. Identity fields
  (names, tags, logins, emails, URLs) also reject every invisible format character
  (Unicode Cf: zero-width spaces/joiners, LRM/RLM, soft hyphen, tag characters...).
- Secrets are NEVER normalized or stripped (a leading space may be intentional). They are
  only checked for type, length and control/bidi characters.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any
from urllib.parse import urlsplit

from vaultkeeper.config import constants as c
from vaultkeeper.errors import ValidationError

# Bidi embedding/override/isolate characters can visually disguise text ("Trojan Source").
_BIDI_CONTROLS = frozenset("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


# --- Generic helpers --------------------------------------------------------------------------


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(field, "must be text")
    return value


def _check_characters(value: str, field: str, *, multiline: bool,
                      identity: bool = False) -> None:
    allowed_controls = {"\n", "\t"} if multiline else set()
    for ch in value:
        category = unicodedata.category(ch)
        if ch in _BIDI_CONTROLS or ch == "\ufeff" or (identity and category == "Cf"):
            raise ValidationError(field, "contains invisible formatting characters")
        if category == "Cs" or (category == "Cc" and ch not in allowed_controls):
            raise ValidationError(field, "contains control characters")


def check_length(value: str, field: str, max_len: int) -> None:
    """Raise ValidationError if ``value`` is longer than ``max_len`` characters."""
    if len(value) > max_len:
        raise ValidationError(field, f"must be at most {max_len} characters")


def strip_format_characters(text: str) -> str:
    """``text`` without invisible format characters (Unicode Cf)."""
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def clean_text(
    value: Any, field: str, max_len: int, *, required: bool = False, multiline: bool = False,
    identity: bool = False,
) -> str:
    """Normalize (NFC), strip and check a plain-text value.

    ``identity`` (names, logins, emails, URLs): also reject invisible format characters, so
    two values that look the same are the same (SEC-Low3).
    """
    text = unicodedata.normalize("NFC", _require_str(value, field))
    if multiline:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()
    _check_characters(text, field, multiline=multiline, identity=identity)
    check_length(text, field, max_len)
    if required and not text:
        raise ValidationError(field, "is required")
    return text


def clean_optional_text(value: Any, field: str, max_len: int, *,
                        identity: bool = False) -> str | None:
    """Like ``clean_text`` but ``None``/empty becomes ``None``."""
    if value is None:
        return None
    return clean_text(value, field, max_len, identity=identity) or None


def clean_secret(value: Any, field: str, *, required: bool = False) -> str:
    """Check a secret WITHOUT altering it (no strip, no normalization)."""
    secret = _require_str(value, field)
    _check_characters(secret, field, multiline=False)
    check_length(secret, field, c.MAX_SECRET)
    if required and not secret:
        raise ValidationError(field, "is required")
    return secret


def clean_optional_secret(value: Any, field: str) -> str | None:
    """Like ``clean_secret`` but ``None``/empty becomes ``None``."""
    if value is None:
        return None
    return clean_secret(value, field) or None


def clean_uuid(value: Any, field: str) -> str:
    """Require a canonical UUID string."""
    text = _require_str(value, field)
    try:
        parsed = uuid.UUID(text)
    except ValueError:
        raise ValidationError(field, "is not a valid id") from None
    if str(parsed) != text:
        raise ValidationError(field, "is not a valid id")
    return text


# --- Specific fields ---------------------------------------------------------------------------


def clean_email(value: Any, field: str, *, required: bool = False) -> str:
    """Strip and check an email address with a deliberately simple rule."""
    text = clean_text(value, field, c.MAX_EMAIL, required=required, identity=True)
    if text and not _EMAIL_RE.match(text):
        raise ValidationError(field, "is not a valid email address")
    return text


def clean_optional_email(value: Any, field: str) -> str | None:
    """Like ``clean_email`` but ``None``/empty becomes ``None``."""
    if value is None:
        return None
    return clean_email(value, field) or None


def clean_url(value: Any, field: str) -> str | None:
    """Accept only http(s) URLs with a host. Empty becomes ``None``."""
    text = clean_optional_text(value, field, c.MAX_URL, identity=True)
    if text is None:
        return None
    if any(ch.isspace() for ch in text):
        raise ValidationError(field, "must not contain spaces")
    try:
        parts = urlsplit(text)
    except ValueError:
        raise ValidationError(field, "is not a valid URL") from None
    if parts.scheme.lower() not in _ALLOWED_URL_SCHEMES or not parts.netloc:
        raise ValidationError(field, "must be an http:// or https:// address")
    return text
