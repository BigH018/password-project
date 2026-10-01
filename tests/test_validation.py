"""Input validation: limits, control characters, secrets untouched, field rules, whole account."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fake_data import make_account, make_game
from vaultkeeper.config import constants as c
from vaultkeeper.core import validation as v
from vaultkeeper.core.models import Rank
from vaultkeeper.errors import ValidationError

# --- Text -------------------------------------------------------------------------------------


def test_clean_text_strips_and_normalizes() -> None:
    assert v.clean_text("  Cafe\u0301  ", "f", 20) == "Caf\u00e9"


@pytest.mark.parametrize("bad", ["a\x00b", "a\x1bb", "a\nb", "a\u202eb", "\ufeffab", "a\x7fb"])
def test_clean_text_rejects_control_and_bidi(bad: str) -> None:
    with pytest.raises(ValidationError):
        v.clean_text(bad, "f", 50)


def test_multiline_allows_newlines_and_normalizes_crlf() -> None:
    assert v.clean_text("line1\r\nline2\tx", "notes", 50, multiline=True) == "line1\nline2\tx"


def test_length_limit_and_required() -> None:
    with pytest.raises(ValidationError):
        v.clean_text("x" * 11, "f", 10)
    with pytest.raises(ValidationError):
        v.clean_text("   ", "f", 10, required=True)
    with pytest.raises(ValidationError):
        v.clean_text(123, "f", 10)


def test_error_message_never_contains_value() -> None:
    secret_looking = "Fake-Secret\x00Value"
    with pytest.raises(ValidationError) as info:
        v.clean_secret(secret_looking, "password")
    assert "Fake-Secret" not in str(info.value)
    assert info.value.field == "password"


def test_emoji_names_allowed() -> None:
    # Zero-width joiner (category Cf) is used inside emoji and must not be rejected.
    assert v.clean_text("Pro\U0001f469\u200d\U0001f4bb", "display_name", 64)


# --- Secrets ----------------------------------------------------------------------------------


def test_secret_is_not_stripped_or_normalized() -> None:
    raw = "  Cafe\u0301 pass "
    assert v.clean_secret(raw, "password") == raw


@pytest.mark.parametrize("bad", ["pa\nss", "pa\x00ss", "pa\u202ess"])
def test_secret_rejects_controls(bad: str) -> None:
    with pytest.raises(ValidationError):
        v.clean_secret(bad, "password")


def test_secret_length_limit() -> None:
    v.clean_secret("x" * c.MAX_SECRET, "password")
    with pytest.raises(ValidationError):
        v.clean_secret("x" * (c.MAX_SECRET + 1), "password")


def test_optional_secret_empty_is_none() -> None:
    assert v.clean_optional_secret("", "email_password") is None
    assert v.clean_optional_secret(None, "email_password") is None


# --- Fields -----------------------------------------------------------------------------------


@pytest.mark.parametrize("good", ["a@example.test", "first.last+alt@mail.example.com"])
def test_email_valid(good: str) -> None:
    assert v.clean_email(f" {good} ", "email") == good


@pytest.mark.parametrize("bad", ["no-at-sign", "a@b", "a@@example.test", "a b@example.test"])
def test_email_invalid(bad: str) -> None:
    with pytest.raises(ValidationError):
        v.clean_email(bad, "email")


def test_url_rules() -> None:
    assert v.clean_url("https://mail.example.test/login", "u") == "https://mail.example.test/login"
    assert v.clean_url("", "u") is None
    for bad in ("javascript:alert(1)", "file:///C:/x", "ftp://example.test", "https://",
                "https://exa mple.test", "mail.example.test"):
        with pytest.raises(ValidationError):
            v.clean_url(bad, "u")


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
        v.clean_uuid("not-a-uuid", "id")
    with pytest.raises(ValidationError):
        v.clean_uuid("6F9619FF-8B86-D011-B42D-00C04FC964FF", "id")  # non-canonical case
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
