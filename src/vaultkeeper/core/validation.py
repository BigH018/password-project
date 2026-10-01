"""Input validation and normalization at the service boundary.

Every ``clean_*`` function returns a normalized value or raises ``ValidationError`` naming the
field and a generic reason. Error messages never include the rejected value.

- Plain text is NFC-normalized and stripped. Control characters (except newline/tab in
  multi-line notes) and bidirectional override characters are rejected.
- Secrets are NEVER normalized or stripped (a leading space may be intentional). They are
  only checked for type, length and control/bidi characters.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from vaultkeeper.config import constants as c
from vaultkeeper.core.models import Account, Rank
from vaultkeeper.errors import ValidationError

# Bidi embedding/override/isolate characters can visually disguise text ("Trojan Source").
_BIDI_CONTROLS = frozenset("‪‫‬‭‮⁦⁧⁨⁩")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$")
_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


# --- Generic helpers --------------------------------------------------------------------------


def _require_str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(field, "must be text")
    return value


def _check_characters(value: str, field: str, *, multiline: bool) -> None:
    allowed_controls = {"\n", "\t"} if multiline else set()
    for ch in value:
        if ch in _BIDI_CONTROLS or ch == "﻿":
            raise ValidationError(field, "contains invisible formatting characters")
        category = unicodedata.category(ch)
        if category == "Cs" or (category == "Cc" and ch not in allowed_controls):
            raise ValidationError(field, "contains control characters")


def _check_length(value: str, field: str, max_len: int) -> None:
    if len(value) > max_len:
        raise ValidationError(field, f"must be at most {max_len} characters")


def clean_text(
    value: Any, field: str, max_len: int, *, required: bool = False, multiline: bool = False
) -> str:
    """Normalize (NFC), strip and check a plain-text value."""
    text = unicodedata.normalize("NFC", _require_str(value, field))
    if multiline:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.strip()
    _check_characters(text, field, multiline=multiline)
    _check_length(text, field, max_len)
    if required and not text:
        raise ValidationError(field, "is required")
    return text


def clean_optional_text(value: Any, field: str, max_len: int) -> str | None:
    """Like ``clean_text`` but ``None``/empty becomes ``None``."""
    if value is None:
        return None
    return clean_text(value, field, max_len) or None


def clean_secret(value: Any, field: str, *, required: bool = False) -> str:
    """Check a secret WITHOUT altering it (no strip, no normalization)."""
    secret = _require_str(value, field)
    _check_characters(secret, field, multiline=False)
    _check_length(secret, field, c.MAX_SECRET)
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
    text = clean_text(value, field, c.MAX_EMAIL, required=required)
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
    text = clean_optional_text(value, field, c.MAX_URL)
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


def clean_display_name(value: Any) -> str:
    """In-game name. Must not contain '#' (the tag has its own field)."""
    text = clean_text(value, "display_name", c.MAX_DISPLAY_NAME)
    if "#" in text:
        raise ValidationError("display_name", "must not contain '#'; put the tag in the tag field")
    return text


def clean_tag(value: Any) -> str | None:
    """Tag after '#'. A leading '#' is removed. No spaces or further '#'."""
    text = clean_optional_text(value, "tag", c.MAX_TAG + 1)
    if text is None:
        return None
    text = text.removeprefix("#")
    _check_length(text, "tag", c.MAX_TAG)
    if not text:
        return None
    if "#" in text or any(ch.isspace() for ch in text):
        raise ValidationError("tag", "must not contain spaces or '#'")
    return text


def split_tagged_id(text: str) -> tuple[str, str | None]:
    """Split ``name#tag`` at the LAST '#'. Returns ``(name, tag_or_None)``, both stripped."""
    name, sep, tag = text.rpartition("#")
    if not sep:
        return text.strip(), None
    return name.strip(), (tag.strip() or None)


def clean_labels(values: Any) -> tuple[str, ...]:
    """Free-form labels. Trimmed, empties dropped, de-duplicated case-insensitively."""
    if isinstance(values, str) or not isinstance(values, Iterable):
        raise ValidationError("tags", "must be a list of labels")
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        label = clean_text(raw, "tags", c.MAX_LABEL)
        if not label:
            continue
        if "," in label:
            raise ValidationError("tags", "a label must not contain commas")
        key = label.casefold()
        if key not in seen:
            seen.add(key)
            result.append(label)
    if len(result) > c.MAX_LABELS:
        raise ValidationError("tags", f"at most {c.MAX_LABELS} labels allowed")
    return tuple(result)


def clean_status(value: Any) -> str:
    """Status must be one of ``constants.STATUSES``."""
    if value not in c.STATUSES:
        raise ValidationError("status", "is not a valid status")
    return str(value)


def clean_region(value: Any, preset: c.GamePreset) -> str | None:
    """Region must be in the preset's region list. Empty becomes ``None``."""
    text = clean_optional_text(value, "region", c.MAX_REGION)
    if text is not None and text not in preset.regions:
        raise ValidationError("region", "is not a region for this game")
    return text


def clean_rank(rank: Any, preset: c.GamePreset) -> Rank:
    """Tier must exist in the preset. Division is optional but, if given, must be in range."""
    if not isinstance(rank, Rank):
        raise ValidationError("rank", "is not a rank")
    if rank.tier is None:
        if rank.division is not None:
            raise ValidationError("rank", "unranked accounts cannot have a division")
        return rank
    spec = preset.tier(rank.tier)
    if spec is None:
        raise ValidationError("rank", "is not a rank tier for this game")
    if rank.division is not None and rank.division not in spec.divisions:
        raise ValidationError("rank", "division is not valid for this tier")
    return rank


def clean_totp_secret(value: Any) -> str | None:
    """Base32 TOTP secret. Spaces/hyphens are removed and letters uppercased. Empty → None."""
    if value is None:
        return None
    secret = clean_secret(value, "totp_secret")
    compact = "".join(ch for ch in secret if ch not in " -").upper()
    if not compact:
        return None
    if not _BASE32_RE.match(compact):
        raise ValidationError("totp_secret", "must be a base32 key (letters A-Z and digits 2-7)")
    if not c.MIN_TOTP_SECRET <= len(compact.rstrip("=")) <= c.MAX_TOTP_SECRET:
        raise ValidationError("totp_secret", "has an invalid length")
    return compact


def clean_game_name(value: Any) -> str:
    """Game name: required, single line."""
    return clean_text(value, "game_name", c.MAX_GAME_NAME, required=True)


def clean_preset_key(value: Any) -> str:
    """Preset key must be a known preset."""
    if value not in c.PRESETS:
        raise ValidationError("preset", "is not a known game preset")
    return str(value)


# --- Whole account ----------------------------------------------------------------------------


def validate_account(account: Account, preset: c.GamePreset) -> Account:
    """Return a normalized copy of ``account`` or raise ``ValidationError``.

    An account needs at least one identifier: login username, in-game name or email.
    """
    cleaned = replace(
        account,
        id=clean_uuid(account.id, "id"),
        game_id=clean_uuid(account.game_id, "game_id"),
        display_name=clean_display_name(account.display_name),
        tag=clean_tag(account.tag),
        login_username=clean_text(account.login_username, "login_username", c.MAX_LOGIN),
        password=clean_secret(account.password, "password"),
        email=clean_email(account.email, "email"),
        email_password=clean_optional_secret(account.email_password, "email_password"),
        email_login_url=clean_url(account.email_login_url, "email_login_url"),
        region=clean_region(account.region, preset),
        rank=clean_rank(account.rank, preset),
        status=clean_status(account.status),
        recovery_email=clean_optional_email(account.recovery_email, "recovery_email"),
        totp_secret=clean_totp_secret(account.totp_secret),
        tags=clean_labels(account.tags),
        notes=clean_text(account.notes, "notes", c.MAX_NOTES, multiline=True),
    )
    if not (cleaned.login_username or cleaned.display_name or cleaned.email):
        raise ValidationError("account", "needs a login username, in-game name or email")
    if cleaned.tag and not cleaned.display_name:
        raise ValidationError("tag", "needs an in-game name")
    return cleaned
