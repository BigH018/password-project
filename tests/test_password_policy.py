"""Master password policy (enforced) and strength hint (advisory)."""

from __future__ import annotations

import time

import pytest

from vaultkeeper.core import password_policy as pp
from vaultkeeper.errors import WeakPasswordError


@pytest.mark.parametrize(
    "good",
    ["correct horse fake staple", "Fake-Passw0rd-12", "lamp orbit cactus tide", "  spaced fake  "],
)
def test_accepted(good: str) -> None:
    assert pp.check_master_password(good) == good


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        ("", "required"),
        ("short-pass1", "at least 12"),
        ("aaaaaaaaaaaaaaaa", "different characters"),
        ("abababababab", "different characters"),
        ("Password1234", "too easy to guess"),
        ("fake\npassphrase!", "control"),
    ],
)
def test_rejected(bad: str, reason: str) -> None:
    with pytest.raises(WeakPasswordError, match=reason) as info:
        pp.check_master_password(bad)
    assert info.value.field == "master_password"
    if bad:
        assert bad not in str(info.value)


@pytest.mark.parametrize(
    "phrase",
    [
        "my password is a purple lamp", "letmein to the castle gate", "qwerty keyboard on a boat",
        "valorant overwatch rivals alts", "password1234 but much longer here",
        "Password 1234", "administrator of llamas",
    ],
)
def test_reasonable_passphrases_with_common_words_pass(phrase: str) -> None:
    assert pp.check_master_password(phrase) == phrase


def test_common_rejection_message_is_generic() -> None:
    with pytest.raises(WeakPasswordError) as info:
        pp.check_master_password("Password1234")
    message = str(info.value).lower()
    assert "common" not in message and "list" not in message
    assert "password1234" not in message
    assert message == "master_password: is too easy to guess; try a longer passphrase"


def test_exactly_min_length_ok() -> None:
    assert pp.check_master_password("Fake-pass-12")  # 12 chars


def test_passphrase_scores_higher_than_short_password() -> None:
    weak = pp.strength_hint("abcd1234efgh")
    strong = pp.strength_hint("lamp orbit cactus tide river")
    assert strong.score > weak.score
    assert strong.score >= 3


def test_hint_suggests_passphrase_when_no_words() -> None:
    hint = pp.strength_hint("Xk9#mQ2!pL")
    assert any("passphrase" in s for s in hint.suggestions)
    assert any("12" in s for s in hint.suggestions)


def test_hint_flags_sequences_and_repeats() -> None:
    assert any("sequence" in s for s in pp.strength_hint("qwertyuiop12").suggestions)
    assert any("repeat" in s for s in pp.strength_hint("aaaaaaaabbbbbbbb").suggestions)


def test_hint_never_contains_password() -> None:
    pw = "lamp orbit cactus tide"
    hint = pp.strength_hint(pw)
    assert pw not in repr(hint)


def test_empty_password_hint() -> None:
    hint = pp.strength_hint("")
    assert hint.score == 0 and hint.label == "Very weak"


def test_long_input_is_fast() -> None:
    start = time.perf_counter()
    pp.strength_hint("abcdefghij" * 100)
    pp.check_master_password("x1y2z3w4v5" * 100)
    assert time.perf_counter() - start < 0.5


def test_sequence_detection() -> None:
    assert pp._sequence_penalty("xxabcdxx") == 4
    assert pp._sequence_penalty("zyxw") == 4
    assert pp._sequence_penalty("abc") == 0
    assert pp._sequence_penalty("a1b2c3d4") == 0
