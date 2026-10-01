"""Password generator: length, character classes, ambiguity, randomness source."""

from __future__ import annotations

import string

import pytest

from vaultkeeper.core import generator as g
from vaultkeeper.errors import ValidationError


@pytest.mark.parametrize("length", [8, 20, 64, 128])
def test_length(length: int) -> None:
    assert len(g.generate(g.GeneratorOptions(length=length))) == length


def test_every_chosen_class_appears() -> None:
    for _ in range(200):
        pw = g.generate(g.GeneratorOptions(length=8))
        assert any(c.islower() for c in pw) and any(c.isupper() for c in pw)
        assert any(c.isdigit() for c in pw) and any(c in g.SYMBOLS for c in pw)


def test_only_chosen_classes() -> None:
    opts = g.GeneratorOptions(length=40, uppercase=False, symbols=False)
    for _ in range(50):
        assert set(g.generate(opts)) <= set(string.ascii_lowercase + string.digits)


def test_avoid_ambiguous() -> None:
    opts = g.GeneratorOptions(length=128, avoid_ambiguous=True)
    for _ in range(20):
        assert not set(g.generate(opts)) & g.AMBIGUOUS
    loose = g.GeneratorOptions(length=128, avoid_ambiguous=False, symbols=False)
    seen = set().union(*(g.generate(loose) for _ in range(50)))
    assert seen & {"l", "1", "O", "0"}


def test_passwords_differ() -> None:
    assert len({g.generate() for _ in range(100)}) == 100


@pytest.mark.parametrize("opts", [
    g.GeneratorOptions(length=7),
    g.GeneratorOptions(length=129),
    g.GeneratorOptions(lowercase=False, uppercase=False, digits=False, symbols=False),
])
def test_invalid_options(opts: g.GeneratorOptions) -> None:
    with pytest.raises(ValidationError):
        g.generate(opts)


def test_entropy() -> None:
    assert g.entropy_bits(g.GeneratorOptions(length=20)) > 100
    assert g.entropy_bits(g.GeneratorOptions(length=8, uppercase=False, symbols=False,
                                             lowercase=False)) < 30


def test_uses_secrets_not_random() -> None:
    source = open(g.__file__, encoding="utf-8").read()
    assert "import secrets" in source and "import random" not in source
