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


def test_uuid_and_game_name() -> None:
    with pytest.raises(ValidationError):
        t.clean_uuid("not-a-uuid", "id")
    with pytest.raises(ValidationError):
        t.clean_uuid("6F9619FF-8B86-D011-B42D-00C04FC964FF", "id")  # non-canonical case
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


# --- CR-M3: name#tag typed into the name with the tag empty is split --------------------


@pytest.mark.parametrize(
    ("name", "tag", "expected"),
    [("FakePlayer#TEST", None, ("FakePlayer", "TEST")),
     ("FakePlayer#TEST", "  ", ("FakePlayer", "TEST")),
     ("FakePlayer", None, ("FakePlayer", None)),
     ("FakePlayer#TEST", "EUW", ("FakePlayer#TEST", "EUW"))],  # tag given: not guessed
)
def test_split_name_and_tag(name: str, tag: str | None,
                            expected: tuple[str, str | None]) -> None:
    assert v.split_name_and_tag(name, tag) == expected


def test_validate_account_splits_name_and_tag() -> None:
    game = make_game()
    account = make_account(game, display_name="FakePlayer#TEST", tag=None)
    cleaned = v.validate_account(account, game.template)
    assert (cleaned.display_name, cleaned.tag) == ("FakePlayer", "TEST")
    with pytest.raises(ValidationError):  # both filled in: still the user's call
        v.validate_account(replace(account, tag="EUW"), game.template)


# --- SEC-Low3: no invisible format characters (Unicode Cf) in identity fields -------------
INVISIBLE = {
    "LRM": chr(0x200E), "RLM": chr(0x200F), "ZWSP": chr(0x200B), "ZWNJ": chr(0x200C),
    "ZWJ": chr(0x200D), "word joiner": chr(0x2060), "soft hyphen": chr(0xAD),
    "tag A": chr(0xE0041), "tag cancel": chr(0xE007F),
}  # fmt: skip


@pytest.mark.parametrize("char", INVISIBLE.values(), ids=INVISIBLE.keys())
def test_identity_fields_reject_invisible_characters(char: str) -> None:
    game = make_game()
    base = make_account(game)
    cases = {
        "display_name": replace(base, display_name=f"Fake{char}Player"),
        "tag": replace(base, tag=f"TE{char}ST"),
        "login_username": replace(base, login_username=f"fake{char}login"),
        "email": replace(base, email=f"fake{char}@example.test"),
        "recovery_email": replace(base, recovery_email=f"backup{char}@example.test"),
        "email_login_url": replace(base, email_login_url=f"https://mail.exam{char}ple.test/"),
    }
    for field, account in cases.items():
        with pytest.raises(ValidationError) as info:
            v.validate_account(account, game.template)
        assert info.value.field == field
        assert "invisible" in info.value.reason
    with pytest.raises(ValidationError):
        v.clean_game_name(f"Valo{char}rant")


def test_notes_and_labels_keep_emoji_sequences() -> None:
    family = chr(0x1F468) + chr(0x200D) + chr(0x1F469)  # emoji joined with ZWJ
    game = make_game()
    account = replace(make_account(game), notes=f"main {family}", tags=(f"fam {family}",))
    cleaned = v.validate_account(account, game.template)
    assert family in cleaned.notes and family in cleaned.tags[0]


def test_secrets_are_still_never_altered() -> None:
    game = make_game()
    secret = "Fake" + chr(0x200B) + "Passw0rd-1!"
    cleaned = v.validate_account(replace(make_account(game), password=secret), game.template)
    assert cleaned.password == secret

