"""GameService: add, rename, preset change rules, delete blocking, rollback on save failure."""

from __future__ import annotations

import pytest

from conftest import FakeStore
from fake_data import make_account
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.game_template import CustomField, FieldKind, GameTemplate, TierDef
from vaultkeeper.core.models import Rank, new_id
from vaultkeeper.errors import (
    DuplicateGameError,
    GameInUseError,
    NotFoundError,
    ValidationError,
    VaultIOError,
)


@pytest.fixture
def games(store: FakeStore) -> GameService:
    return GameService(store)


def test_add_and_list_sorted(games: GameService, store: FakeStore) -> None:
    games.add("valorant", "valorant")
    games.add("Apex Legends")
    games.add("Overwatch", "overwatch")
    assert [g.name for g in games.list_games()] == ["Apex Legends", "Overwatch", "valorant"]
    assert games.list_games()[0].template == GameTemplate()  # blank
    assert store.saves == 3


def test_add_trims_and_rejects_duplicates_case_insensitively(games: GameService) -> None:
    game = games.add("  Valorant  ", "valorant")
    assert game.name == "Valorant"
    with pytest.raises(DuplicateGameError):
        games.add("VALORANT")


@pytest.mark.parametrize(("name", "preset"), [("", "custom"), ("x" * 65, "custom"),
                                              ("bad\x00name", "custom")])
def test_add_invalid(games: GameService, name: str, preset: str) -> None:
    with pytest.raises(ValidationError):
        games.add(name, preset)


def test_rename(games: GameService, store: FakeStore) -> None:
    val = games.add("Valorant", "valorant")
    games.add("Overwatch", "overwatch")
    renamed = games.rename(val.id, "VALORANT")  # case change of own name is fine
    assert renamed.name == "VALORANT" and renamed.id == val.id
    assert games.get(val.id).name == "VALORANT"
    with pytest.raises(DuplicateGameError):
        games.rename(val.id, "overwatch")
    with pytest.raises(NotFoundError):
        games.rename("00000000-0000-4000-8000-000000000000", "X")


def test_delete_empty_game(games: GameService, store: FakeStore) -> None:
    game = games.add("Valorant", "valorant")
    games.delete(game.id)
    assert games.list_games() == []
    with pytest.raises(NotFoundError):
        games.delete(game.id)


def test_delete_blocked_with_count(games: GameService, store: FakeStore) -> None:
    game = games.add("Valorant", "valorant")
    store.data.accounts.extend([make_account(game, n=1), make_account(game, n=2)])
    with pytest.raises(GameInUseError, match="2 accounts"):
        games.delete(game.id)
    assert games.get(game.id) == game


def test_account_counts(games: GameService, store: FakeStore) -> None:
    a = games.add("Valorant", "valorant")
    b = games.add("Overwatch", "overwatch")
    store.data.accounts.append(make_account(a))
    assert games.account_counts() == {a.id: 1, b.id: 0}


def test_set_template_never_blocked_and_keeps_account_data(games: GameService,
                                                          store: FakeStore) -> None:
    game = games.add("Valorant", "valorant")
    account = make_account(game, region="EU", rank=Rank("Ascendant", 2))
    store.data.accounts.append(account)
    smaller = GameTemplate(tiers=(TierDef("Gold", 3),), regions=("NA",))
    updated = games.set_template(game.id, smaller)
    assert updated.template.tiers == (TierDef("Gold", 3),)
    assert store.data.accounts == [account]  # nothing deleted or rewritten


def test_set_template_validates(games: GameService) -> None:
    game = games.add("Fortnite")
    for bad in (
        GameTemplate(tiers=(TierDef("Gold"), TierDef("gold"))),  # duplicate rank
        GameTemplate(tiers=(TierDef(""),)),                        # empty name
        GameTemplate(tiers=(TierDef("Gold", 11),)),                # too many divisions
        GameTemplate(regions=("EU", "eu")),
        GameTemplate(custom_fields=(CustomField(new_id(), "Level", FieldKind.CHOICE),)),
        GameTemplate(hidden_fields=frozenset({"password"})),       # can't hide a core field
    ):
        with pytest.raises(ValidationError):
            games.set_template(game.id, bad)
    assert games.get(game.id).template == GameTemplate()


def test_add_with_starter_or_template(games: GameService) -> None:
    ow = games.add("Overwatch", "overwatch")
    assert ow.template.tiers[0] == TierDef("Bronze", 5) and ow.template.best_division_is_one
    custom = games.add("Fortnite", GameTemplate(tiers=(TierDef("Bronze", 3), TierDef("Unreal"))))
    assert [t.name for t in custom.template.tiers] == ["Bronze", "Unreal"]
    assert games.add("Blank").template == GameTemplate()


def test_failed_save_rolls_back(games: GameService, store: FakeStore) -> None:
    game = games.add("Valorant", "valorant")
    store.fail_next_save = True
    with pytest.raises(VaultIOError):
        games.add("Overwatch", "overwatch")
    assert [g.name for g in games.list_games()] == ["Valorant"]
    store.fail_next_save = True
    with pytest.raises(VaultIOError):
        games.rename(game.id, "Renamed")
    assert games.get(game.id).name == "Valorant"
    store.fail_next_save = True
    with pytest.raises(VaultIOError):
        games.delete(game.id)
    assert games.get(game.id) == game
