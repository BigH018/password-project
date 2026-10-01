"""Password generator. All randomness comes from ``secrets`` (never ``random``)."""

from __future__ import annotations

import math
import secrets
import string
from dataclasses import dataclass

from vaultkeeper.errors import ValidationError

MIN_LENGTH = 8
MAX_LENGTH = 128
DEFAULT_LENGTH = 20
SYMBOLS = "!@#$%^&*()-_=+[]{};:,.?/~"
AMBIGUOUS = frozenset("Il1O0o|`'\"")


@dataclass(frozen=True, slots=True)
class GeneratorOptions:
    """What the generated password may contain."""

    length: int = DEFAULT_LENGTH
    lowercase: bool = True
    uppercase: bool = True
    digits: bool = True
    symbols: bool = True
    avoid_ambiguous: bool = True


def _classes(options: GeneratorOptions) -> list[str]:
    chosen = []
    if options.lowercase:
        chosen.append(string.ascii_lowercase)
    if options.uppercase:
        chosen.append(string.ascii_uppercase)
    if options.digits:
        chosen.append(string.digits)
    if options.symbols:
        chosen.append(SYMBOLS)
    if options.avoid_ambiguous:
        chosen = ["".join(ch for ch in group if ch not in AMBIGUOUS) for group in chosen]
    return [group for group in chosen if group]


def check_options(options: GeneratorOptions) -> list[str]:
    """Validate options and return the character groups to use."""
    if not MIN_LENGTH <= options.length <= MAX_LENGTH:
        raise ValidationError("length", f"must be {MIN_LENGTH} to {MAX_LENGTH}")
    groups = _classes(options)
    if not groups:
        raise ValidationError("character_types", "choose at least one kind of character")
    if len(groups) > options.length:
        raise ValidationError("length", "is too short for the chosen character types")
    return groups


def generate(options: GeneratorOptions = GeneratorOptions()) -> str:  # noqa: B008
    """A random password with at least one character from every chosen group."""
    groups = check_options(options)
    alphabet = "".join(groups)
    chars = [secrets.choice(group) for group in groups]  # one of each group
    chars += [secrets.choice(alphabet) for _ in range(options.length - len(chars))]
    # Fisher-Yates shuffle with secrets so the guaranteed characters aren't up front.
    for i in range(len(chars) - 1, 0, -1):
        j = secrets.randbelow(i + 1)
        chars[i], chars[j] = chars[j], chars[i]
    return "".join(chars)


def entropy_bits(options: GeneratorOptions) -> int:
    """Approximate strength of passwords made with these options."""
    alphabet = "".join(check_options(options))
    return int(options.length * math.log2(len(set(alphabet))))
