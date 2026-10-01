"""Field rules (names, tags, labels, presets, ranks, TOTP) and whole-account validation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fake_data import make_account, make_game
from vaultkeeper.config import constants as c
from vaultkeeper.core import text_validation as t
from vaultkeeper.core import validation as v
from vaultkeeper.core.models import Rank
from vaultkeeper.errors import ValidationError

# --- Fields -----------------------------------------------------------------------------------


def test_display_name_rejects_hash() -> None:
    with pytest.raises(ValidationError):
        v.clean_display_name("Name#TAG")


def test_tag_rules() -> None:
    assert v.clean_tag("#EUW") == "EUW"
    assert v.clean_tag("  ") is None
    assert v.clean_tag("#") is None
    for bad in ("A B", "A#B", "x" * (c.MAX_TAG + 1)):
        with pytest.raises(ValidationError):
            v.clean_tag(bad)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Name#TAG", ("Name", "TAG")), ("Name", ("Name", None)), ("A#B#C", ("A#B", "C")),
     (" Name # TAG ", ("Name", "TAG")), ("Name#", ("Name", None))],
)
def test_split_tagged_id(text: str, expected: tuple[str, str | None]) -> None:
    assert v.split_tagged_id(text) == expected


def test_labels_dedupe_and_rules() -> None:
    assert v.clean_labels([" Main ", "main", "", "smurf"]) == ("Main", "smurf")
    with pytest.raises(ValidationError):
        v.clean_labels("not-a-list")
    with pytest.raises(ValidationError):
        v.clean_labels(["a,b"])
    with pytest.raises(ValidationError):
        v.clean_labels([f"l{i}" for i in range(c.MAX_LABELS + 1)])


def test_status_and_region() -> None:
    assert v.clean_status("banned") == "banned"
    with pytest.raises(ValidationError):
        v.clean_status("deleted")
    assert v.clean_region("EU", c.VALORANT) == "EU"
    assert v.clean_region("", c.VALORANT) is None
    with pytest.raises(ValidationError):
        v.clean_region("Europe", c.VALORANT)


@pytest.mark.parametrize(
    "rank", [Rank(), Rank("Gold", 2), Rank("Gold", None), Rank("Radiant", None)]
)
def test_rank_valid(rank: Rank) -> None:
    assert v.clean_rank(rank, c.VALORANT) == rank


@pytest.mark.parametrize(
    "rank", [Rank(None, 1), Rank("Grandmaster", 1), Rank("Gold", 4), Rank("Radiant", 1)]
)
def test_rank_invalid(rank: Rank) -> None:
    with pytest.raises(ValidationError):
        v.clean_rank(rank, c.VALORANT)


def test_overwatch_division_5_valid_valorant_division_5_invalid() -> None:
    assert v.clean_rank(Rank("Gold", 5), c.OVERWATCH)
    with pytest.raises(ValidationError):
        v.clean_rank(Rank("Gold", 5), c.VALORANT)


def test_custom_preset_free_text_rank_and_region() -> None:
    assert v.clean_rank(Rank("  Elite III ", None), c.CUSTOM) == Rank("Elite III", None)
    assert v.clean_rank(Rank("", None), c.CUSTOM) == Rank(None, None)
    assert v.clean_region("Any Server", c.CUSTOM) == "Any Server"
    with pytest.raises(ValidationError):
        v.clean_rank(Rank("Gold", 2), c.CUSTOM)
    with pytest.raises(ValidationError):
        v.clean_rank(Rank("x" * (c.MAX_TIER + 1), None), c.CUSTOM)
    with pytest.raises(ValidationError):
        v.clean_region("bad\x00region", c.CUSTOM)


def test_totp_secret() -> None:
    assert v.clean_totp_secret("jbsw y3dp-ehpk 3pxp") == "JBSWY3DPEHPK3PXP"
    assert v.clean_totp_secret("") is None
    for bad in ("JBSWY3DP", "JBSWY3DPEHPK3PX1", "!!!!!!!!!!!!!!!!"):
        with pytest.raises(ValidationError):
            v.clean_totp_secret(bad)


def test_uuid_and_preset_and_game_name() -> None:
    with pytest.raises(ValidationError):
        t.clean_uuid("not-a-uuid", "id")
    with pytest.raises(ValidationError):
        t.clean_uuid("6F9619FF-8B86-D011-B42D-00C04FC964FF", "id")  # non-canonical case
    assert v.clean_preset_key("overwatch") == "overwatch"
    with pytest.raises(ValidationError):
        v.clean_preset_key("fortnite")
    with pytest.raises(ValidationError):
        v.clean_game_name("  ")


# --- Whole account ----------------------------------------------------------------------------


def test_validate_account_normalizes() -> None:
    game = make_game()
    account = make_account(game, display_name="  Fake  ", tag="#TEST", email=" a@example.test ",
                           tags=["x", "X"], notes="a\r\nb ")
    cleaned = v.validate_account(account, c.VALORANT)
    assert (cleaned.display_name, cleaned.tag, cleaned.email) == ("Fake", "TEST", "a@example.test")
    assert cleaned.tags == ("x",)
    assert cleaned.notes == "a\nb"
    assert cleaned.password == account.password


def test_validate_account_needs_an_identifier() -> None:
    account = make_account(make_game(), display_name="", tag=None, login_username="", email="")
    with pytest.raises(ValidationError) as info:
        v.validate_account(account, c.VALORANT)
    assert info.value.field == "account"


def test_validate_account_tag_needs_name() -> None:
    account = make_account(make_game(), display_name="", tag="TEST")
    with pytest.raises(ValidationError):
        v.validate_account(account, c.VALORANT)


def test_validate_account_checks_preset() -> None:
    account = make_account(make_game(), region="Europe")
    with pytest.raises(ValidationError):
        v.validate_account(account, c.VALORANT)
    overwatch_account = replace(account, rank=Rank("Master", 4))
    assert v.validate_account(overwatch_account, c.OVERWATCH).region == "Europe"
