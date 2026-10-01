"""Master password policy and a simple, dependency-free strength hint.

Enforced (raises WeakPasswordError): at least 12 characters, at least 5 distinct
characters, not EXACTLY (case-insensitively) one of a short list of very common passwords,
no control characters. The list only matches whole passwords, so a passphrase that merely
contains a common word is never rejected. The rejection message stays generic.
Everything else is advice: the hint nudges toward a passphrase of random words.

The strength estimate is a rough heuristic for UI feedback, not a security guarantee.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from vaultkeeper.config.constants import MASTER_PASSWORD_MIN_LENGTH
from vaultkeeper.core.text_validation import clean_secret
from vaultkeeper.errors import ValidationError, WeakPasswordError

MIN_DISTINCT_CHARS = 5
STRONG_BITS = 80
GOOD_BITS = 60
FAIR_BITS = 45

_COMMON = frozenset({
    "password1234", "password12345", "password123456", "passwordpassword", "123456789012",
    "1234567890123", "qwertyuiopas", "qwerty123456", "iloveyou1234", "letmein12345",
    "welcome12345", "administrator", "abcdefghijkl", "abc123456789", "trustno1trustno1",
    "valorant1234", "overwatch123", "masterpassword", "changeme1234", "passw0rd1234",
})  # fmt: skip
_SEQUENCES = ("abcdefghijklmnopqrstuvwxyz", "qwertyuiopasdfghjklzxcvbnm", "01234567890")
_WORD_SEPARATORS = re.compile(r"[\s\-_.]+")

LABELS = ("Very weak", "Weak", "Fair", "Good", "Strong")


@dataclass(frozen=True, slots=True)
class StrengthHint:
    """UI feedback: score 0-4, a label and suggestions (never contains the password)."""

    score: int
    label: str
    estimated_bits: int
    suggestions: tuple[str, ...]


def check_master_password(password: str) -> str:
    """Return the password unchanged if it meets the policy, else raise WeakPasswordError."""
    try:
        clean_secret(password, "master_password", required=True)
    except ValidationError as exc:
        raise WeakPasswordError(exc.reason) from None
    if len(password) < MASTER_PASSWORD_MIN_LENGTH:
        raise WeakPasswordError(f"must be at least {MASTER_PASSWORD_MIN_LENGTH} characters")
    if len(set(password)) < MIN_DISTINCT_CHARS:
        raise WeakPasswordError("uses too few different characters")
    if password.casefold() in _COMMON:
        raise WeakPasswordError("is too easy to guess; try a longer passphrase")
    return password


def _pool_size(password: str) -> int:
    pool = 0
    if any(ch.islower() for ch in password):
        pool += 26
    if any(ch.isupper() for ch in password):
        pool += 26
    if any(ch.isdigit() for ch in password):
        pool += 10
    if any(not ch.isalnum() and ch.isascii() for ch in password):
        pool += 33
    if any(not ch.isascii() for ch in password):
        pool += 100
    return max(pool, 1)


def _longest_run(text: str, seq: str) -> int:
    """Longest run of characters that step forward or backward through ``seq`` (linear)."""
    best = run = 1
    direction = 0
    for a, b in zip(text, text[1:], strict=False):
        ia, ib = seq.find(a), seq.find(b)
        step = ib - ia if ia >= 0 and ib >= 0 else 0
        if step in (1, -1):
            run = run + 1 if (run == 1 or step == direction) else 2
            direction = step
        else:
            run, direction = 1, 0
        best = max(best, run)
    return best


def _sequence_penalty(password: str) -> int:
    """Length of the longest alphabet/keyboard/digit run of 4+ characters, else 0."""
    lowered = password.lower()
    longest = max(_longest_run(lowered, seq) for seq in _SEQUENCES)
    return longest if longest >= 4 else 0


def _words(password: str) -> list[str]:
    return [w for w in _WORD_SEPARATORS.split(password) if len(w) >= 3]


def estimate_bits(password: str) -> int:
    """Rough entropy estimate: charset size x effective length, minus easy patterns."""
    if not password:
        return 0
    effective = len(password) - _sequence_penalty(password) // 2
    repeats = len(password) - len(set(password))
    effective -= repeats // 3
    bits = max(effective, 1) * math.log2(_pool_size(password))
    if len(_words(password)) >= 4:
        bits = max(bits, 4 * 11)  # 4+ words: assume at least a small-wordlist passphrase
    return int(bits)


def strength_hint(password: str) -> StrengthHint:
    """Return a score/label and suggestions for the create/change password dialogs."""
    bits = estimate_bits(password)
    score = (
        4 if bits >= STRONG_BITS else 3 if bits >= GOOD_BITS else 2 if bits >= FAIR_BITS
        else 1 if bits >= 28 else 0
    )  # fmt: skip
    suggestions: list[str] = []
    if len(password) < MASTER_PASSWORD_MIN_LENGTH:
        suggestions.append(f"Use at least {MASTER_PASSWORD_MIN_LENGTH} characters.")
    if len(_words(password)) < 4:
        suggestions.append(
            "Try a passphrase: 4 or more random, unrelated words (e.g. 'lamp orbit cactus tide')."
        )
    if _sequence_penalty(password) >= 4:
        suggestions.append("Avoid keyboard or alphabet sequences.")
    if len(set(password)) < len(password) // 2:
        suggestions.append("Avoid repeating characters.")
    return StrengthHint(score, LABELS[score], bits, tuple(suggestions))
