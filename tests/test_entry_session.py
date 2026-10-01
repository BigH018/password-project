"""EntrySession: sticky values carry over, region only within a game, counter."""

from __future__ import annotations

from fake_data import make_account, make_game
from vaultkeeper.core.entry_session import EntrySession
from vaultkeeper.core.models import Account, new_id


def test_defaults() -> None:
    session = EntrySession()
    assert session.added == 0 and session.counter_text() == "0 added this session"


def test_remember_and_next_draft_same_game() -> None:
    game = make_game()
    session = EntrySession()
    session.remember(make_account(game, region="EU", status="banned"))
    draft = session.next_draft(Account(id=new_id(), game_id=game.id))
    assert (draft.region, draft.status) == ("EU", "banned")
    assert draft.display_name == "" and draft.login_username == ""
    assert session.counter_text() == "1 added this session"


def test_region_does_not_carry_to_another_game() -> None:
    val, ow = make_game("Valorant", "valorant"), make_game("Overwatch", "overwatch")
    session = EntrySession()
    session.remember(make_account(val, region="EU", status="locked"))
    draft = session.next_draft(Account(id=new_id(), game_id=ow.id))
    assert draft.region is None and draft.status == "locked"


def test_counter_counts_every_save() -> None:
    game = make_game()
    session = EntrySession()
    for n in range(43):
        session.remember(make_account(game, n=n))
    assert session.counter_text() == "43 added this session"


def test_starting_game_prefers_the_selected_game() -> None:
    session = EntrySession()
    assert session.starting_game_id(None) is None
    assert session.starting_game_id("selected-game") == "selected-game"
    session.remember(make_account(make_game("Overwatch", "overwatch")))
    batch_game = session.game_id
    assert session.starting_game_id(None) == batch_game  # "All games": last batch game
    assert session.starting_game_id("selected-game") == "selected-game"  # a game is selected
