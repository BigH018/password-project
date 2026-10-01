"""Paste assist: turn one pasted block of text into field SUGGESTIONS. Never saves anything.

Rules, deliberately simple and predictable:
1. Labeled lines win: ``user:``/``login:``, ``pass:``/``password:``, ``email:``,
   ``email pass:``, ``recovery:``, ``riot id:``/``ign:``/``name:``, ``tag:``, ``region:``,
   ``rank:``, ``status:``, and any extra field's own label (e.g. ``Platform: PC``).
2. The VALUES of login/password lines are never scanned by the other rules (a password that
   contains "@" or "Gold" is not mistaken for an email or a rank).
3. Unlabeled text: a token with "@" -> email; ``name#tag`` -> name + tag; a rank word from the
   game's ladder (optionally followed by a division) -> rank; a region from the game's list ->
   region; the word "banned" -> status banned + a note.

Input is size-limited and cleaned of control characters. Secret values (passwords, secret
extra fields) are kept exactly as pasted; everything else is NFC-normalized. Nothing here
is logged.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from vaultkeeper.config.constants import GamePreset
from vaultkeeper.core.game_template import FieldKind, GameTemplate
from vaultkeeper.core.models import Rank
from vaultkeeper.core.text_validation import _BIDI_CONTROLS

MAX_PASTE = 5000
_BOM = chr(0xFEFF)  # byte-order mark (invisible); chr() keeps this file ASCII-only

_LABELS: dict[str, str] = {
    "user": "login_username", "username": "login_username", "login": "login_username",
    "user name": "login_username", "acc": "login_username", "account": "login_username",
    "pass": "password", "password": "password", "pw": "password", "pwd": "password",
    "email": "email", "mail": "email", "e-mail": "email",
    "email pass": "email_password", "email password": "email_password",
    "mail pass": "email_password", "email pw": "email_password",
    "recovery": "recovery_email", "recovery email": "recovery_email",
    "riot id": "riot_id", "riot": "riot_id", "ign": "riot_id", "name": "riot_id",
    "battletag": "riot_id", "tag": "tag", "region": "region", "server": "region",
    "rank": "rank", "elo": "rank", "status": "status", "notes": "notes", "note": "notes",
}  # fmt: skip
_SECRET_TARGETS = {"login_username", "password", "email_password"}  # values not re-scanned
_RAW_TARGETS = {"password", "email_password"}  # stored exactly as pasted (never normalized)

# Short forms people write in notes. Used only if the full name is in the game's ladder.
_TIER_ALIASES = {
    "plat": "Platinum", "dia": "Diamond", "diam": "Diamond", "asc": "Ascendant",
    "imm": "Immortal", "immo": "Immortal", "rad": "Radiant", "gm": "Grandmaster",
    "masters": "Master", "celest": "Celestial", "oaa": "One Above All", "t500": "Top 500",
    "top500": "Top 500", "champ": "Champion", "eter": "Eternity",
}  # fmt: skip
# Region codes and the names different games use for them (first match in the game wins).
_REGION_ALIASES = {
    "eu": ("EU", "Europe", "EUW", "EU West"), "euw": ("EUW", "EU West", "EU", "Europe"),
    "na": ("NA", "Americas", "NA East", "NA West"), "us": ("NA", "Americas"),
    "ap": ("AP", "Asia", "APAC"), "asia": ("Asia", "AP"), "kr": ("KR", "Korea", "Asia"),
    "br": ("BR", "SA", "Americas"), "latam": ("LATAM", "SA", "Americas"),
    "oce": ("OCE", "Asia", "AP"), "me": ("ME", "Middle East"),
}  # fmt: skip
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9,
          "x": 10}
_LABEL_LINE = re.compile(r"^\s*([A-Za-z][A-Za-z \-]{0,24}?)\s*[:=]\s*(.*)$")
_EMAIL = re.compile(r"[^\s@<>()\[\],;:\"']+@[^\s@<>()\[\],;:\"']+\.[A-Za-z]{2,}")
_TAGGED = re.compile(r"(?<![\w@#])([^\s#@:,;]{2,16})#([A-Za-z0-9]{2,5})(?![\w#])")
_BANNED = re.compile(r"\b(perma ?)?banned\b", re.IGNORECASE)


@dataclass
class PasteSuggestions:
    """What paste assist found. ``fields`` uses Account field names (plus ``extra``)."""

    fields: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, str] = field(default_factory=dict)  # custom field id -> value
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def describe(self) -> list[str]:
        """Human-readable list of what was found (secret values are never included)."""
        names = {
            "display_name": "name", "tag": "tag", "login_username": "username",
            "password": "password", "email": "email", "email_password": "email password",
            "recovery_email": "recovery email", "region": "region", "rank": "rank",
            "status": "status", "notes": "notes",
        }  # fmt: skip
        found = [names.get(k, k) for k in self.fields]
        if self.extra:
            found.append(f"{len(self.extra)} extra field(s)")
        return found


def _clean(text: str) -> str:
    """Limit size, unify newlines, drop control characters. NOT normalized (see ``_nfc``)."""
    text = text[:MAX_PASTE].replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch for ch in text if ch in "\n\t" or (
        unicodedata.category(ch) != "Cc" and ch not in _BIDI_CONTROLS and ch != _BOM))


def _nfc(text: str) -> str:
    """NFC for matching and plain-text values. Never applied to secrets: a pasted password
    must be stored exactly as pasted, or it may not match the real one."""
    return unicodedata.normalize("NFC", text)


def _tier_lookup(preset: GamePreset) -> dict[str, str]:
    lookup = {name.casefold(): name for name in preset.tier_names}
    for alias, full in _TIER_ALIASES.items():
        if full in preset.tier_names:
            lookup.setdefault(alias, full)
    return lookup


def find_rank(text: str, preset: GamePreset) -> Rank | None:
    """First ladder tier mentioned in ``text`` (longest names first), plus a valid division."""
    lookup = _tier_lookup(preset)
    for key in sorted(lookup, key=len, reverse=True):
        match = re.search(rf"(?<![\w]){re.escape(key)}(?![\w])\s*([0-9]{{1,2}}|[ivx]{{1,4}})?\b",
                          text, re.IGNORECASE)
        if not match:
            continue
        tier = lookup[key]
        spec = preset.tier(tier)
        raw = (match.group(1) or "").casefold()
        division = int(raw) if raw.isdigit() else _ROMAN.get(raw)
        if spec is None or division not in spec.divisions:
            division = None
        return Rank(tier, division)
    return None


def find_region(text: str, regions: tuple[str, ...]) -> str | None:
    """A region of this game mentioned as a whole word (codes like EU/NA map to its names)."""
    for region in sorted(regions, key=len, reverse=True):
        if re.search(rf"(?<![\w]){re.escape(region)}(?![\w])", text, re.IGNORECASE):
            return region
    for code, candidates in _REGION_ALIASES.items():
        if re.search(rf"(?<![\w]){code}(?![\w])", text, re.IGNORECASE):
            for candidate in candidates:
                if candidate in regions:
                    return candidate
    return None


def _apply_label(target: str, value: str, result: PasteSuggestions, preset: GamePreset) -> None:
    fields = result.fields
    if target == "riot_id":
        name, _sep, tag = value.rpartition("#") if "#" in value else (value, "", "")
        fields.setdefault("display_name", name.strip())
        if tag.strip():
            fields.setdefault("tag", tag.strip())
    elif target == "rank":
        rank = find_rank(value, preset)
        if rank is not None:
            fields.setdefault("rank", rank)
        else:
            result.warnings.append("The rank in the pasted text isn't in this game's list.")
    elif target == "region":
        region = find_region(value, preset.regions)
        if region is not None:
            fields.setdefault("region", region)
        else:
            result.warnings.append("The region in the pasted text isn't in this game's list.")
    elif target == "status":
        status = value.strip().casefold()
        if status in ("active", "banned", "locked", "retired"):
            fields.setdefault("status", status)
    elif target == "notes":
        result.notes.append(value)
    elif target == "tag":
        fields.setdefault("tag", value.lstrip("#"))
    else:
        fields.setdefault(target, value)


def suggest(text: str, template: GameTemplate) -> PasteSuggestions:
    """Suggestions for one pasted account block. The caller decides what to apply."""
    result = PasteSuggestions()
    preset = template.to_preset()
    extra_by_label = {_nfc(f.label).casefold(): f for f in template.custom_fields}
    free: list[str] = []  # unlabeled text, plus values of non-secret labeled lines
    for line in _clean(text).split("\n"):
        if not line.strip():
            continue
        match = _LABEL_LINE.match(line)
        label = _nfc(match.group(1)).strip().casefold() if match else ""
        raw = match.group(2).strip() if match else ""
        if match and label in _LABELS:
            target = _LABELS[label]
            value = raw if target in _RAW_TARGETS else _nfc(raw)
            if value:
                _apply_label(target, value, result, preset)
            if target not in _SECRET_TARGETS:
                free.append(value)
        elif match and label in extra_by_label:
            custom = extra_by_label[label]
            if raw:
                keep_raw = custom.kind is FieldKind.SECRET
                result.extra.setdefault(custom.id, raw if keep_raw else _nfc(raw))
        else:
            free.append(_nfc(line))
    _scan_free_text("\n".join(free), result, preset)
    return result


def _scan_free_text(text: str, result: PasteSuggestions, preset: GamePreset) -> None:
    fields = result.fields
    emails = _EMAIL.findall(text)
    if emails:
        fields.setdefault("email", emails[0])
        if len(emails) > 1 and "recovery_email" not in fields:
            fields["recovery_email"] = emails[1]
    without_emails = _EMAIL.sub(" ", text)
    tagged = _TAGGED.search(without_emails)
    if tagged and "display_name" not in fields:
        fields["display_name"], fields["tag"] = tagged.group(1), tagged.group(2)
    if "rank" not in fields:
        rank = find_rank(without_emails, preset)
        if rank is not None:
            fields["rank"] = rank
    if "region" not in fields:
        region = find_region(without_emails, preset.regions)
        if region is not None:
            fields["region"] = region
    if _BANNED.search(without_emails):
        fields.setdefault("status", "banned")
        result.notes.append("Banned (from pasted text).")
