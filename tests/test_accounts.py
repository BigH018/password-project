"""AccountService: CRUD, validation, timestamps, moving games, rollback, duplicates."""

from __future__ import annotations

from dataclasses import replace

import pytest

from conftest import FakeStore
from fake_data import make_account, make_game
from vaultkeeper.core.account_service import AccountService, DuplicateField
from vaultkeeper.core.models import Account, Game, Rank
from vaultkeeper.errors import NotFoundError, ValidationError, VaultIOError

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-02-01T00:00:00+00:00"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> str:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def valorant(store: FakeStore) -> Game:
    game = make_game("Valorant", "valorant")
    store.data.games.append(game)
    return game


@pytest.fixture
def overwatch(store: FakeStore) -> Game:
    game = make_game("Overwatch", "overwatch")
    store.data.games.append(game)
    return game


@pytest.fixture
def accounts(store: FakeStore, clock: Clock) -> AccountService:
    return AccountService(store, clock=clock)


def _draft(svc: AccountService, game: Game, **fields: object) -> Account:
    base = make_account(game)
    values = {k: getattr(base, k) for k in ("display_name", "tag", "login_username", "password",
                                             "email", "region", "rank", "status", "tags")}
    values.update(fields)
    return replace(svc.new_draft(game.id), **values)


def test_add_sets_timestamps_and_normalizes(accounts: AccountService, valorant: Game,
                                           store: FakeStore) -> None:
    added = accounts.add(_draft(accounts, valorant, display_name="  Alt  ", tag="#EUW"))
    assert (added.display_name, added.tag) == ("Alt", "EUW")
    assert added.created_at == added.updated_at == T0
    assert accounts.get(added.id) == added
    assert store.saves == 1


def test_add_validates_against_preset(accounts: AccountService, valorant: Game) -> None:
    with pytest.raises(ValidationError):
        accounts.add(_draft(accounts, valorant, region="Europe"))
    with pytest.raises(ValidationError):
        accounts.add(_draft(accounts, valorant, rank=Rank("Champion", 1)))
    assert accounts.list_all() == []


def test_add_rejects_unknown_game_and_duplicate_id(accounts: AccountService,
                                                   valorant: Game) -> None:
    with pytest.raises(ValidationError):
        accounts.new_draft("00000000-0000-4000-8000-000000000000")
    added = accounts.add(_draft(accounts, valorant))
    with pytest.raises(ValidationError):
        accounts.add(added)


def test_update_preserves_created_at(accounts: AccountService, valorant: Game,
                                     clock: Clock) -> None:
    added = accounts.add(_draft(accounts, valorant))
    clock.now = T1
    updated = accounts.update(replace(added, status="banned", created_at="tampered",
                                      notes="Banned for testing."))
    assert updated.created_at == T0 and updated.updated_at == T1
    assert accounts.get(added.id).status == "banned"


def test_move_to_other_game_revalidates(accounts: AccountService, valorant: Game,
                                        overwatch: Game) -> None:
    added = accounts.add(_draft(accounts, valorant, region="EU", rank=Rank("Gold", 2)))
    with pytest.raises(ValidationError):
        accounts.update(replace(added, game_id=overwatch.id))  # EU isn't an OW region
    moved = accounts.update(replace(added, game_id=overwatch.id, region="Europe",
                                    rank=Rank("Gold", 5)))
    assert moved.game_id == overwatch.id
    assert accounts.list_for_game(overwatch.id) == [moved]
    assert accounts.list_for_game(valorant.id) == []


def test_update_and_delete_missing(accounts: AccountService, valorant: Game) -> None:
    ghost = _draft(accounts, valorant)
    with pytest.raises(NotFoundError):
        accounts.update(ghost)
    with pytest.raises(NotFoundError):
        accounts.delete(ghost.id)


def test_delete(accounts: AccountService, valorant: Game) -> None:
    a = accounts.add(_draft(accounts, valorant, login_username="one"))
    b = accounts.add(_draft(accounts, valorant, login_username="two"))
    accounts.delete(a.id)
    assert accounts.list_all() == [b]


def test_failed_save_rolls_back(accounts: AccountService, valorant: Game,
                                store: FakeStore) -> None:
    a = accounts.add(_draft(accounts, valorant))
    before = store.data.updated_at
    for action in (
        lambda: accounts.add(_draft(accounts, valorant, login_username="other")),
        lambda: accounts.update(replace(a, status="retired")),
        lambda: accounts.delete(a.id),
    ):
        store.fail_next_save = True
        with pytest.raises(VaultIOError):
            action()
        assert accounts.list_all() == [a]
        assert store.data.updated_at == before


# --- duplicates -------------------------------------------------------------------------------


def test_duplicate_login_case_and_whitespace(accounts: AccountService, valorant: Game) -> None:
    existing = accounts.add(_draft(accounts, valorant, login_username="Fake_Login"))
    candidate = _draft(accounts, valorant, login_username="  fake_login ", display_name="Other")
    matches = accounts.find_duplicates(candidate)
    assert [(m.account_id, m.field) for m in matches] == [(existing.id, DuplicateField.LOGIN)]


def test_duplicate_riot_id(accounts: AccountService, valorant: Game) -> None:
    existing = accounts.add(_draft(accounts, valorant, display_name="Alt", tag="EUW",
                                   login_username="a1"))
    same = _draft(accounts, valorant, display_name="alt", tag="euw", login_username="a2")
    other_tag = _draft(accounts, valorant, display_name="Alt", tag="NA1", login_username="a3")
    assert [m.field for m in accounts.find_duplicates(same)] == [DuplicateField.RIOT_ID]
    assert accounts.find_duplicates(other_tag) == []
    assert accounts.find_duplicates(same)[0].account_id == existing.id


def test_missing_tag_counts_as_empty(accounts: AccountService, valorant: Game) -> None:
    accounts.add(_draft(accounts, valorant, display_name="Solo", tag=None, login_username="s1"))
    assert accounts.find_duplicates(
        _draft(accounts, valorant, display_name="solo", tag=None, login_username="s2"))
    assert not accounts.find_duplicates(
        _draft(accounts, valorant, display_name="solo", tag="X1", login_username="s3"))


def test_duplicates_ignore_other_games_self_and_blanks(accounts: AccountService, valorant: Game,
                                                       overwatch: Game) -> None:
    existing = accounts.add(_draft(accounts, valorant, login_username="shared"))
    assert accounts.find_duplicates(existing) == []  # editing doesn't flag itself
    other_game = _draft(accounts, overwatch, login_username="shared", region=None,
                        rank=Rank())
    assert accounts.find_duplicates(other_game) == []
    blank = _draft(accounts, valorant, login_username="", display_name="", tag=None)
    assert accounts.find_duplicates(blank) == []


def test_duplicates_work_on_unvalidated_drafts(accounts: AccountService, valorant: Game) -> None:
    accounts.add(_draft(accounts, valorant, login_username="typing"))
    half_typed = replace(accounts.new_draft(valorant.id), login_username="TYPING",
                         display_name="has#hash")  # invalid name, still checkable
    assert accounts.find_duplicates(half_typed)
