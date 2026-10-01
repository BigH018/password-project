"""Field and whole-account validation rules (game presets, ranks, labels, TOTP, ...).

Generic text helpers live in ``core/text_validation.py``. Error messages never include the
rejected value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from vaultkeeper.config import constants as c
from vaultkeeper.core.game_template import GameTemplate, template_from_preset
from vaultkeeper.core.models import Account, Rank
from vaultkeeper.core.template_validation import clean_extra
from vaultkeeper.core.text_validation import (
    check_length,
    clean_email,
    clean_optional_email,
    clean_optional_secret,
    clean_optional_text,
    clean_secret,
    clean_text,
    clean_url,
    clean_uuid,
)
from vaultkeeper.errors import ValidationError

_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$")


# --- Field rules -------------------------------------------------------------------------------


def clean_display_name(value: Any) -> str:
    """In-game name. Must not contain '#' (the tag has its own field)."""
    text = clean_text(value, "display_name", c.MAX_DISPLAY_NAME, identity=True)
    if "#" in text:
        raise ValidationError("display_name", "must not contain '#'; put the tag in the tag field")
    return text


def clean_tag(value: Any) -> str | None:
    """Tag after '#'. A leading '#' is removed. No spaces or further '#'."""
    text = clean_optional_text(value, "tag", c.MAX_TAG + 1, identity=True)
    if text is None:
        return None
    text = text.removeprefix("#")
    check_length(text, "tag", c.MAX_TAG)
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


def split_name_and_tag(name: str, tag: str | None) -> tuple[str, str | None]:
    """``name#tag`` typed into the name while the tag is empty -> ``(name, tag)``.

    A tag that is already filled in is never guessed over: the pair is returned unchanged.
    """
    if (tag or "").strip() or "#" not in name:
        return name, tag
    return split_tagged_id(name)


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


def clean_region(value: Any, preset: c.GamePreset, previous: str | None = None) -> str | None:
    """Region must be in the game's region list (any text for free-text presets).

    A value no longer in the list is accepted if unchanged from ``previous`` (kept data).
    """
    text = clean_optional_text(value, "region", c.MAX_REGION)
    if text is not None and text == previous:
        return text
    if text is not None and not preset.free_text and text not in preset.regions:
        raise ValidationError("region", "is not a region for this game")
    return text


def clean_rank(rank: Any, preset: c.GamePreset, previous: Rank | None = None) -> Rank:
    """Tier must exist in the ladder. Division is optional but, if given, must be in range.

    Free-text presets accept any tier text and no division. A rank no longer in the ladder
    is accepted if unchanged from ``previous`` (kept data).
    """
    if not isinstance(rank, Rank):
        raise ValidationError("rank", "is not a rank")
    if previous is not None and rank == previous:
        return rank
    if preset.free_text:
        if rank.division is not None:
            raise ValidationError("rank", "free-text ranks have no division")
        return Rank(clean_optional_text(rank.tier, "rank", c.MAX_TIER), None)
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
    """Base32 TOTP secret. Spaces/hyphens are removed and letters uppercased. Empty -> None."""
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
    return clean_text(value, "game_name", c.MAX_GAME_NAME, required=True, identity=True)


# --- Whole account ----------------------------------------------------------------------------


def validate_account(
    account: Account,
    template: GameTemplate | c.GamePreset,
    previous: Account | None = None,
) -> Account:
    """Return a normalized copy of ``account`` or raise ``ValidationError``.

    ``template`` is the game's template (a built-in preset is accepted and converted).
    ``previous`` is the stored version of the same account in the same game: values that
    are no longer in the template are allowed only if unchanged from it.
    An account needs at least one identifier: login username, in-game name or email.
    """
    if isinstance(template, c.GamePreset):
        preset = template
        template = GameTemplate() if template.free_text else template_from_preset(template)
    else:
        preset = template.to_preset()
    name, tag = account.display_name, account.tag
    if isinstance(name, str) and (tag is None or isinstance(tag, str)):
        name, tag = split_name_and_tag(name, tag)
    cleaned = replace(
        account,
        id=clean_uuid(account.id, "id"),
        game_id=clean_uuid(account.game_id, "game_id"),
        display_name=clean_display_name(name),
        tag=clean_tag(tag),
        login_username=clean_text(account.login_username, "login_username", c.MAX_LOGIN,
                                  identity=True),
        password=clean_secret(account.password, "password"),
        email=clean_email(account.email, "email"),
        email_password=clean_optional_secret(account.email_password, "email_password"),
        email_login_url=clean_url(account.email_login_url, "email_login_url"),
        region=clean_region(account.region, preset, previous.region if previous else None),
        rank=clean_rank(account.rank, preset, previous.rank if previous else None),
        status=clean_status(account.status),
        recovery_email=clean_optional_email(account.recovery_email, "recovery_email"),
        totp_secret=clean_totp_secret(account.totp_secret),
        tags=clean_labels(account.tags),
        notes=clean_text(account.notes, "notes", c.MAX_NOTES, multiline=True),
        extra=clean_extra(account.extra, template, previous.extra if previous else ()),
    )
    if not (cleaned.login_username or cleaned.display_name or cleaned.email):
        raise ValidationError("account", "needs a login username, in-game name or email")
    if cleaned.tag and not cleaned.display_name:
        raise ValidationError("tag", "needs an in-game name")
    return cleaned
