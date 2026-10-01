"""Search/filter: each criterion, combinations, secrets never searched, rank ordering, speed."""

from __future__ import annotations

import time

import pytest

from fake_data import FAKE_PASSWORD, make_account, make_game
from vaultkeeper.config import constants as c
from vaultkeeper.core.models import Account, Game, Rank
from vaultkeeper.core.search import (
    UNRANKED,
    AccountFilter,
    facets,
    filter_accounts,
    matches,
    rank_label,
    rank_sort_key,
)

VAL = make_game("Valorant", "valorant")
OW = make_game("Overwatch", "overwatch")


@pytest.fixture
def pool() -> list[Account]:
    return [
        make_account(VAL, n=1, display_name="Alpha", tag="EUW", region="EU",
                     rank=Rank("Gold", 2), status="active", tags=("main",),
                     notes="Has the rare skin."),
        make_account(VAL, n=2, display_name="Bravo", tag="NA1", region="NA",
                     rank=Rank("Radiant", None), status="banned", tags=("smurf", "Main")),
        make_account(VAL, n=3, display_name="Charlie", tag=None, region="EU", rank=Rank(),
                     status="retired", tags=()),
        make_account(OW, n=4, display_name="Delta", tag="1234", region="Europe",
                     rank=Rank("Gold", 5), status="active", tags=("smurf",)),
    ]


def _names(accounts: list[Account]) -> list[str]:
    return [a.display_name for a in accounts]


def test_empty_filter_matches_all(pool: list[Account]) -> None:
    assert AccountFilter().is_empty
    assert filter_accounts(pool, AccountFilter()) == pool


@pytest.mark.parametrize(
    ("flt", "expected"),
    [
        (AccountFilter(game_id=VAL.id), ["Alpha", "Bravo", "Charlie"]),
        (AccountFilter(statuses=frozenset({"banned", "retired"})), ["Bravo", "Charlie"]),
        (AccountFilter(tiers=frozenset({"Gold"})), ["Alpha", "Delta"]),
        (AccountFilter(tiers=frozenset({UNRANKED})), ["Charlie"]),
        (AccountFilter(regions=frozenset({"EU"})), ["Alpha", "Charlie"]),
        (AccountFilter(tags=frozenset({"MAIN"})), ["Alpha", "Bravo"]),
        (AccountFilter(tags=frozenset({"main", "smurf"})), ["Bravo"]),
        (AccountFilter(game_id=VAL.id, tiers=frozenset({"Gold"})), ["Alpha"]),
    ],
)
def test_criteria(pool: list[Account], flt: AccountFilter, expected: list[str]) -> None:
    assert not flt.is_empty
    assert _names(filter_accounts(pool, flt)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("alpha", ["Alpha"]),
        ("ALPHA#euw", ["Alpha"]),
        ("rare skin", ["Alpha"]),            # notes, all words required
        ("skin rare", ["Alpha"]),
        ("rare banned", []),
        ("player2@example", ["Bravo"]),      # email
        ("fake_login_3", ["Charlie"]),       # login
        ("banned", ["Bravo"]),               # status
        ("radiant", ["Bravo"]),              # rank
        ("unranked", ["Charlie"]),
        ("europe", ["Delta"]),               # region
        ("smurf", ["Bravo", "Delta"]),       # label
        ("   ", ["Alpha", "Bravo", "Charlie", "Delta"]),
    ],
)
def test_free_text(pool: list[Account], text: str, expected: list[str]) -> None:
    assert _names(filter_accounts(pool, AccountFilter(text=text))) == expected


def test_secrets_are_never_searched(pool: list[Account]) -> None:
    secret_pool = [make_account(VAL, email_password="Hidden-Mail-Pass",
                                totp_secret="JBSWY3DPEHPK3PXP")]
    for secret in (FAKE_PASSWORD, "Hidden-Mail-Pass", "JBSWY3DPEHPK3PXP", "Passw0rd"):
        assert filter_accounts(pool + secret_pool, AccountFilter(text=secret)) == []


def test_rank_sort_key_orders_by_ladder() -> None:
    ranks = [Rank("Radiant", None), Rank("Gold", 3), Rank(), Rank("Gold", 1), Rank("Iron", 1),
             Rank("Gold", None), Rank("Immortal", 3)]
    ordered = sorted((make_account(VAL, rank=r) for r in ranks),
                     key=lambda a: rank_sort_key(a, c.VALORANT))
    assert [a.rank for a in ordered] == [
        Rank(), Rank("Iron", 1), Rank("Gold", None), Rank("Gold", 1), Rank("Gold", 3),
        Rank("Immortal", 3), Rank("Radiant", None),
    ]


def test_rank_sort_key_overwatch_5_is_lowest() -> None:
    low, high = make_account(OW, rank=Rank("Gold", 5)), make_account(OW, rank=Rank("Gold", 1))
    assert rank_sort_key(low, c.OVERWATCH) < rank_sort_key(high, c.OVERWATCH)


def test_unknown_tiers_sort_after_known_alphabetically() -> None:
    known = make_account(VAL, rank=Rank("Radiant", None))
    zed = make_account(VAL, rank=Rank("Zed", None))
    apex = make_account(VAL, rank=Rank("apex", None))
    ordered = sorted([zed, known, apex], key=lambda a: rank_sort_key(a, c.VALORANT))
    assert ordered == [known, apex, zed]


def test_rank_label() -> None:
    assert rank_label(make_account(VAL, rank=Rank("Gold", 2)), c.VALORANT) == "Gold 2"
    rivals = make_game("Rivals", "marvel_rivals")
    assert rank_label(make_account(rivals, rank=Rank("Gold", 2)), c.MARVEL_RIVALS) == "Gold II"


def test_filter_5000_accounts_fast() -> None:
    games: list[Game] = [VAL, OW]
    many = [
        make_account(games[i % 2], n=i, notes=f"note {i} " * 5,
                     rank=Rank("Gold", 2) if i % 2 == 0 else Rank("Gold", 5),
                     region="EU" if i % 2 == 0 else "Europe")
        for i in range(5000)
    ]
    flt = AccountFilter(text="fakeplayer12 note", statuses=frozenset({"active"}))
    start = time.perf_counter()
    result = filter_accounts(many, flt)
    elapsed = time.perf_counter() - start
    assert result and all(matches(a, flt) for a in result)
    assert elapsed < 0.05, f"filtering took {elapsed:.3f}s"


def test_facets_for_one_game_use_preset_order(pool: list[Account]) -> None:
    f = facets(pool[:3], c.VALORANT)
    assert f.tiers == c.VALORANT.tier_names and f.regions == c.VALORANT.regions
    assert f.tags == ("main", "smurf")  # "Main"/"main" collapse, first spelling kept


def test_facets_across_games_use_present_values(pool: list[Account]) -> None:
    f = facets(pool)
    assert f.tiers == ("Gold", "Radiant")
    assert f.regions == ("EU", "Europe", "NA")


def test_facets_free_text_preset_uses_present_values() -> None:
    apex = make_game("Apex", "custom")
    accounts = [make_account(apex, rank=Rank("Predator", None), region="NA West")]
    f = facets(accounts, c.CUSTOM)
    assert f.tiers == ("Predator",) and f.regions == ("NA West",)
