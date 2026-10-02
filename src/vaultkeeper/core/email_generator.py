"""Email address generator: ``gamename.k7q4@domain``. Randomness comes from ``secrets``.

The address is only made up here, nothing is registered anywhere. It is checked against the
addresses already saved in the vault (``taken``) and drawn again on a clash.
"""

from __future__ import annotations

import secrets
import string
from collections.abc import Collection

from vaultkeeper.config.settings import valid_email_domain
from vaultkeeper.errors import ValidationError

LOOKALIKES = frozenset("lo01")
ALPHABET = "".join(ch for ch in string.ascii_lowercase + string.digits if ch not in LOOKALIKES)
MIN_LENGTH = 4
MAX_LENGTH = 16
DEFAULT_LENGTH = 4
FALLBACK_NAME = "acct"
MAX_LOCAL_PART = 64  # the part before "@" (RFC 5321)
MAX_ATTEMPTS = 1000
_NAME_CHARS = frozenset(string.ascii_lowercase + string.digits)


def game_slug(game_name: str) -> str:
    """Lowercase a-z and 0-9 only ("Marvel Rivals" -> "marvelrivals"); "acct" if empty."""
    return "".join(ch for ch in game_name.lower() if ch in _NAME_CHARS) or FALLBACK_NAME


def random_part(length: int = DEFAULT_LENGTH) -> str:
    """``length`` characters from ``ALPHABET`` (no l, o, 0 or 1)."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def generate_email(game_name: str, domain: str, taken: Collection[str] = (),
                   length: int = DEFAULT_LENGTH) -> str:
    """A new ``slug.random@domain`` that isn't in ``taken`` (compared trimmed, ignoring case)."""
    if not MIN_LENGTH <= length <= MAX_LENGTH:
        raise ValidationError("random_part", f"must be {MIN_LENGTH} to {MAX_LENGTH} characters")
    if not valid_email_domain(domain):
        raise ValidationError("email_domain", "is not a valid domain (e.g. example.com)")
    slug = game_slug(game_name)[: MAX_LOCAL_PART - 1 - length]
    used = {address.strip().casefold() for address in taken}
    for _ in range(MAX_ATTEMPTS):
        email = f"{slug}.{random_part(length)}@{domain}"
        if email not in used:
            return email
    raise ValidationError("random_part",
                          "is too short: every address tried is already in the vault")
