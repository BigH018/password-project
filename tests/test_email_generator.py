"""Email generator: format, game name cleaning, alphabet, domain, duplicates, randomness."""

from __future__ import annotations

import re

import pytest

from vaultkeeper.core import email_generator as eg
from vaultkeeper.core.text_validation import clean_email
from vaultkeeper.errors import ValidationError

DOMAIN = "example.test"


def test_format() -> None:
    email = eg.generate_email("Valorant", DOMAIN)
    assert re.fullmatch(r"valorant\.[a-z0-9]{4}@example\.test", email)
    assert clean_email(email, "email") == email  # passes the vault's own email check


@pytest.mark.parametrize(("name", "slug"), [
    ("Valorant", "valorant"),
    ("Marvel Rivals", "marvelrivals"),
    ("Overwatch 2", "overwatch2"),
    ("  League_of-Legends!  ", "leagueoflegends"),
    ("Caf" + chr(0xE9) + " Game", "cafgame"),  # non a-z letters are dropped, not translated
    ("", "acct"),
    ("!!! ###", "acct"),
])
def test_game_slug(name: str, slug: str) -> None:
    assert eg.game_slug(name) == slug


def test_alphabet_has_no_lookalikes() -> None:
    assert not set(eg.ALPHABET) & {"l", "o", "0", "1"}
    assert set(eg.ALPHABET) <= set("abcdefghijklmnopqrstuvwxyz23456789")
    assert len(eg.ALPHABET) == 32
    seen = set("".join(eg.random_part(16) for _ in range(200)))
    assert seen == set(eg.ALPHABET)


@pytest.mark.parametrize("length", [4, 8, 16])
def test_length(length: int) -> None:
    local = eg.generate_email("Valorant", DOMAIN, length=length).split("@")[0]
    assert len(local.split(".")[1]) == length


@pytest.mark.parametrize("length", [3, 17])
def test_invalid_length(length: int) -> None:
    with pytest.raises(ValidationError) as caught:
        eg.generate_email("Valorant", DOMAIN, length=length)
    assert caught.value.field == "random_part"


@pytest.mark.parametrize("domain", [
    "", "localhost", "Example.test", "exa mple.test", "-bad.test", "bad-.test", "a..test",
    "@example.test", "example.test.", "x" * 64 + ".test", ("a" * 60 + ".") * 2 + "test",
])
def test_invalid_domain(domain: str) -> None:
    with pytest.raises(ValidationError) as caught:
        eg.generate_email("Valorant", domain)
    assert caught.value.field == "email_domain"


def test_long_game_name_keeps_local_part_short() -> None:
    email = eg.generate_email("x" * 200, DOMAIN, length=16)
    assert len(email.split("@")[0]) == eg.MAX_LOCAL_PART
    assert clean_email(email, "email") == email


def test_taken_addresses_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    draws = iter(["aaaa", "bbbb", "cccc"])
    monkeypatch.setattr(eg, "random_part", lambda _length: next(draws))
    taken = {" Valorant.AAAA@Example.test ", "valorant.bbbb@example.test"}
    assert eg.generate_email("Valorant", DOMAIN, taken) == "valorant.cccc@example.test"


def test_gives_up_when_everything_is_taken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(eg, "random_part", lambda _length: "aaaa")
    with pytest.raises(ValidationError) as caught:
        eg.generate_email("Valorant", DOMAIN, {"valorant.aaaa@example.test"})
    assert caught.value.field == "random_part"


def test_addresses_differ() -> None:
    assert len({eg.generate_email("Valorant", DOMAIN, length=8) for _ in range(100)}) == 100


def test_uses_secrets_not_random() -> None:
    source = open(eg.__file__, encoding="utf-8").read()
    assert "import secrets" in source and "import random" not in source
