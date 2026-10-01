"""Paste assist: every rule, false-positive guards, hostile input, per-game templates."""

from __future__ import annotations

from vaultkeeper.config import constants as c
from vaultkeeper.core.game_template import (
    CustomField,
    FieldKind,
    GameTemplate,
    TierDef,
    template_from_preset,
)
from vaultkeeper.core.models import Rank, new_id
from vaultkeeper.core.paste_assist import MAX_PASTE, find_rank, find_region, suggest

VAL = template_from_preset(c.VALORANT)
OW = template_from_preset(c.OVERWATCH)
RIVALS = template_from_preset(c.MARVEL_RIVALS)


def test_labeled_block() -> None:
    block = """
    user: fake_login_7
    pass: Fake-Passw0rd-1!
    email: alt7@example.test
    email pass: Fake-Mail-Pass-2
    recovery: backup7@example.test
    riot id: FakeAlt#EUW1
    region: EU
    rank: Gold 2
    """
    s = suggest(block, VAL)
    assert s.fields == {
        "login_username": "fake_login_7", "password": "Fake-Passw0rd-1!",
        "email": "alt7@example.test", "email_password": "Fake-Mail-Pass-2",
        "recovery_email": "backup7@example.test", "display_name": "FakeAlt", "tag": "EUW1",
        "region": "EU", "rank": Rank("Gold", 2),
    }


def test_unlabeled_rules() -> None:
    s = suggest("FakeAlt#TAG1  alt@example.test  plat 2  na  banned for smurfing", VAL)
    assert s.fields["display_name"] == "FakeAlt" and s.fields["tag"] == "TAG1"
    assert s.fields["email"] == "alt@example.test"
    assert s.fields["rank"] == Rank("Platinum", 2)
    assert s.fields["region"] == "NA"
    assert s.fields["status"] == "banned"
    assert "Banned (from pasted text)." in s.notes


def test_password_value_is_never_scanned() -> None:
    s = suggest("pass: Gold2@example.test#EUW banned\nuser: imm3", VAL)
    assert s.fields == {"password": "Gold2@example.test#EUW banned", "login_username": "imm3"}
    assert s.notes == []


def test_label_beats_heuristics() -> None:
    s = suggest("email: real@example.test\nother@example.test", VAL)
    assert s.fields["email"] == "real@example.test"
    assert s.fields["recovery_email"] == "other@example.test"


def test_region_codes_map_to_each_games_names() -> None:
    assert suggest("eu acc", OW).fields["region"] == "Europe"
    assert suggest("NA", OW).fields["region"] == "Americas"
    assert suggest("KR", VAL).fields["region"] == "KR"
    assert find_region("Asia server", RIVALS.regions) == "Asia"


def test_region_needs_whole_word() -> None:
    assert "region" not in suggest("FakeNAplayer DemoEUalt", VAL).fields


def test_rank_divisions_follow_each_ladder() -> None:
    assert find_rank("Diamond 5", OW.to_preset()) == Rank("Diamond", 5)
    assert find_rank("diamond 5", VAL.to_preset()) == Rank("Diamond", None)  # Val has 1-3
    assert find_rank("Celestial II", RIVALS.to_preset()) == Rank("Celestial", 2)
    assert find_rank("t500", OW.to_preset()) == Rank("Top 500", None)
    assert find_rank("One Above All", RIVALS.to_preset()) == Rank("One Above All", None)
    assert find_rank("radiant", VAL.to_preset()) == Rank("Radiant", None)


def test_rank_needs_whole_word() -> None:
    assert "rank" not in suggest("GoldenBoy99", VAL).fields
    assert "rank" not in suggest("imm3 is my username", OW).fields  # Immortal isn't in OW


def test_unknown_rank_or_region_label_warns() -> None:
    s = suggest("rank: Champion\nregion: Mars", VAL)
    assert "rank" not in s.fields and "region" not in s.fields
    assert len(s.warnings) == 2


def test_custom_template_and_extra_labels() -> None:
    platform = CustomField(new_id(), "Platform", FieldKind.CHOICE, ("PC", "PS5"))
    level = CustomField(new_id(), "Level", FieldKind.NUMBER)
    fortnite = GameTemplate(tiers=(TierDef("Bronze", 3), TierDef("Unreal")),
                            roman_divisions=True, regions=("NA-East", "EU"),
                            custom_fields=(platform, level))
    s = suggest("Platform: PS5\nlevel: 120\nunreal\nna-east", fortnite)
    assert s.extra == {platform.id: "PS5", level.id: "120"}
    assert s.fields["rank"] == Rank("Unreal", None)
    assert s.fields["region"] == "NA-East"


def test_riot_id_with_spaces_via_label() -> None:
    s = suggest("ign: Fake Name With Space#TAG", VAL)
    assert (s.fields["display_name"], s.fields["tag"]) == ("Fake Name With Space", "TAG")


def test_status_label() -> None:
    assert suggest("status: Retired", VAL).fields["status"] == "retired"
    assert "status" not in suggest("status: sleepy", VAL).fields


def test_hostile_input_is_cleaned() -> None:
    zero, bidi, bom = chr(0), chr(0x202E), chr(0xFEFF)
    s = suggest(f"user: fake{zero}_login{bidi}{bom}\nemail: x@example.test", VAL)
    assert s.fields["login_username"] == "fake_login"
    huge = "a" * (MAX_PASTE * 3) + " FakeAlt#TAG"
    assert "display_name" not in suggest(huge, VAL).fields  # truncated before the ID


def test_empty_and_garbage() -> None:
    assert suggest("", VAL).fields == {}
    assert suggest("::::\n=\n  \n", VAL).fields == {}


# --- SEC-Low2: secrets are kept exactly as pasted (no NFC) ----------------------------------
DECOMPOSED = "Fake-Pa" + "e" + chr(0x301) + "ssw0rd-1!"  # "e" + combining acute accent
COMPOSED = "Fake-Pa" + chr(0xE9) + "ssw0rd-1!"


def test_pasted_password_is_not_normalized() -> None:
    found = suggest(f"user: fake_login_1\npass: {DECOMPOSED}\nemail pass: {DECOMPOSED}", VAL)
    assert found.fields["password"] == DECOMPOSED != COMPOSED
    assert found.fields["email_password"] == DECOMPOSED


def test_pasted_secret_extra_field_is_not_normalized() -> None:
    pin = CustomField(id=new_id(), label="Pin", kind=FieldKind.SECRET)
    note = CustomField(id=new_id(), label="Platform", kind=FieldKind.TEXT)
    template = GameTemplate(custom_fields=(pin, note))
    found = suggest(f"Pin: {DECOMPOSED}\nPlatform: {DECOMPOSED}", template)
    assert found.extra[pin.id] == DECOMPOSED
    assert found.extra[note.id] == COMPOSED  # non-secret text is still normalized


def test_non_secret_values_are_still_normalized() -> None:
    name = "Cafe" + chr(0x301)
    found = suggest(f"riot id: {name}#TEST\n{name.lower()}x#AB", VAL)
    assert found.fields["display_name"] == "Caf" + chr(0xE9)


# --- SEC-Low3: identity values copied from web pages lose invisible characters ------------


def test_paste_drops_invisible_characters_from_identity_values() -> None:
    zwsp, shy = chr(0x200B), chr(0xAD)
    pw = "Fake" + zwsp + "Pass-1!"
    found = suggest(f"user: fake{zwsp}_login\npass: {pw}\nemail: alt{shy}7@example.test\n"
                    f"riot id: Fake{zwsp}Alt#TE{shy}ST", VAL)
    assert found.fields["login_username"] == "fake_login"
    assert found.fields["email"] == "alt7@example.test"
    assert (found.fields["display_name"], found.fields["tag"]) == ("FakeAlt", "TEST")
    assert found.fields["password"] == pw  # secrets: exactly as pasted

