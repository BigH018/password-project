"""GameService: add, rename, preset change rules, delete blocking, rollback on save failure."""

from __future__ import annotations

import pytest

from conftest import FakeStore
from fake_data import make_account
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.models import Rank
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
    assert games.list_games()[0].preset == "custom"
    assert store.saves == 3


def test_add_trims_and_rejects_duplicates_case_insensitively(games: GameService) -> None:
    game = games.add("  Valorant  ", "valorant")
    assert game.name == "Valorant"
    with pytest.raises(DuplicateGameError):
        games.add("VALORANT")


@pytest.mark.parametrize(("name", "preset"), [("", "custom"), ("x" * 65, "custom"),
                                              ("Ok", "fortnite"), ("bad\x00name", "custom")])
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


def test_set_preset_allowed_when_all_accounts_fit(games: GameService, store: FakeStore) -> None:
    game = games.add("Rivals")  # custom
    store.data.accounts.append(make_account(game, region="EU", rank=Rank("Gold", None)))
    updated = games.set_preset(game.id, "marvel_rivals")
    assert updated.preset == "marvel_rivals"


def test_set_preset_blocked_with_failure_count(games: GameService, store: FakeStore) -> None:
    game = games.add("Valorant", "valorant")
    store.data.accounts.extend([
        make_account(game, n=1, region="EU", rank=Rank("Ascendant", 2)),  # no Ascendant in OW
        make_account(game, n=2, region="EU", rank=Rank("Gold", 2)),       # EU not an OW region
        make_account(game, n=3, region=None, rank=Rank("Gold", 2)),       # fits Overwatch
    ])
    with pytest.raises(ValidationError, match="2 accounts would become invalid"):
        games.set_preset(game.id, "overwatch")
    assert games.get(game.id).preset == "valorant"


def test_set_preset_singular_message(games: GameService, store: FakeStore) -> None:
    game = games.add("Valorant", "valorant")
    store.data.accounts.append(make_account(game, rank=Rank("Radiant", None)))
    with pytest.raises(ValidationError, match="1 account would"):
        games.set_preset(game.id, "overwatch")


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
