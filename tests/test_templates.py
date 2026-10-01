"""Templates: preset conversion, codec round trip, template validation, extra values, search."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fake_data import make_account, make_game
from vaultkeeper.config import constants as c
from vaultkeeper.core.game_template import (
    CustomField,
    FieldKind,
    GameTemplate,
    TierDef,
    starter_template,
    template_from_preset,
)
from vaultkeeper.core.models import Rank, new_id
from vaultkeeper.core.search import AccountFilter, facets, filter_accounts
from vaultkeeper.core.template_codec import template_from_dict, template_to_dict
from vaultkeeper.core.template_validation import clean_extra, clean_template
from vaultkeeper.core.validation import validate_account
from vaultkeeper.errors import ValidationError, VaultFormatError

LEVEL = CustomField(new_id(), "Level", FieldKind.NUMBER)
MAIN = CustomField(new_id(), "Main", FieldKind.CHOICE, ("Wraith", "Lifeline"))
CODE = CustomField(new_id(), "Backup code", FieldKind.SECRET)
SKINS = CustomField(new_id(), "Skins", FieldKind.TEXT)
GONE = "00000000-0000-4000-8000-000000000000"
FORTNITE = GameTemplate(
    tiers=(TierDef("Bronze", 3), TierDef("Elite"), TierDef("Unreal")),
    best_division_is_one=False, roman_divisions=True, regions=("EU", "NA-East"),
    hidden_fields=frozenset({"tag", "recovery_email"}),
    custom_fields=(LEVEL, MAIN, CODE, SKINS),
)


@pytest.mark.parametrize("preset", [c.VALORANT, c.MARVEL_RIVALS, c.OVERWATCH])
def test_preset_round_trips_through_template(preset: c.GamePreset) -> None:
    back = template_from_preset(preset).to_preset()
    assert back.tier_names == preset.tier_names and back.regions == preset.regions
    assert back.roman_divisions == preset.roman_divisions
    for spec in preset.tiers:
        assert back.tier(spec.name).divisions == spec.divisions  # same low -> high order


def test_starters() -> None:
    assert starter_template("overwatch").best_division_is_one
    assert not starter_template("valorant").best_division_is_one
    assert starter_template("blank") == starter_template("custom") == GameTemplate()


def test_template_helpers() -> None:
    assert not FORTNITE.shows("tag") and FORTNITE.shows("rank")
    assert FORTNITE.custom_field(LEVEL.id) == LEVEL and FORTNITE.custom_field(GONE) is None
    assert FORTNITE.secret_field_ids == {CODE.id}
    assert FORTNITE.searchable_field_ids == {LEVEL.id, MAIN.id, SKINS.id}


def test_codec_round_trip() -> None:
    assert template_from_dict(template_to_dict(FORTNITE), "t") == FORTNITE


def test_codec_rejects_duplicate_field_ids() -> None:
    raw = template_to_dict(replace(FORTNITE, custom_fields=(LEVEL, LEVEL)))
    with pytest.raises(VaultFormatError):
        template_from_dict(raw, "t")


def test_clean_template_normalizes() -> None:
    messy = replace(FORTNITE, tiers=(TierDef("  Bronze ", 3),), regions=(" EU ",))
    cleaned = clean_template(messy)
    assert cleaned.tiers == (TierDef("Bronze", 3),) and cleaned.regions == ("EU",)


@pytest.mark.parametrize("bad", [
    replace(FORTNITE, custom_fields=(LEVEL, replace(LEVEL, id=new_id()))),  # same label
    replace(FORTNITE, custom_fields=(replace(MAIN, choices=()),)),          # empty dropdown
    replace(FORTNITE, custom_fields=(replace(MAIN, choices=("A", "a")),)),  # duplicate option
    replace(FORTNITE, custom_fields=(replace(LEVEL, label=" "),)),
    replace(FORTNITE, custom_fields=(replace(LEVEL, id="not-a-uuid"),)),
])
def test_clean_template_rejects(bad: GameTemplate) -> None:
    with pytest.raises(ValidationError):
        clean_template(bad)


def test_fortnite_ladder_from_template() -> None:
    preset = FORTNITE.to_preset()
    assert preset.tier("Bronze").divisions == (1, 2, 3)  # 3 is the top division
    assert c.format_rank(preset, "Bronze", 3) == "Bronze III"
    assert not preset.tier("Unreal").has_divisions


def test_facets_include_kept_values_after_preset_list() -> None:
    game = make_game("Fortnite", "blank")
    kept = make_account(game, rank=Rank("Champion", None), region="Old Region")
    f = facets([kept], FORTNITE.to_preset())
    assert f.tiers == ("Bronze", "Elite", "Unreal", "Champion")
    assert f.regions == ("EU", "NA-East", "Old Region")


# --- extra values ----------------------------------------------------------------------------


def test_clean_extra_by_kind() -> None:
    raw = ((LEVEL.id, " 42 "), (MAIN.id, "Wraith"), (CODE.id, " keep spaces "), (SKINS.id, ""))
    assert dict(clean_extra(raw, FORTNITE)) == {
        LEVEL.id: "42", MAIN.id: "Wraith", CODE.id: " keep spaces "}


@pytest.mark.parametrize("raw", [
    ((LEVEL.id, "forty"),),
    ((MAIN.id, "Bloodhound"),),
    ((GONE, "new value"),),  # field not in template
    "not a tuple",
])
def test_clean_extra_rejects(raw: object) -> None:
    with pytest.raises(ValidationError):
        clean_extra(raw, FORTNITE)


def test_removed_fields_and_options_are_kept_if_unchanged() -> None:
    previous = ((GONE, "old value"), (MAIN.id, "Bloodhound"))
    assert dict(clean_extra(previous, FORTNITE, previous)) == {
        GONE: "old value", MAIN.id: "Bloodhound"}
    with pytest.raises(ValidationError):  # can't be changed to something new, though
        clean_extra(((GONE, "edited"),), FORTNITE, previous)


def test_validate_account_with_template_and_kept_values() -> None:
    game = make_game("Fortnite", "blank")
    account = make_account(game, tag=None, region="Old Region", rank=Rank("Champion", None),
                           extra=((LEVEL.id, "7"),))
    with pytest.raises(ValidationError):  # brand-new account: old values not allowed
        validate_account(account, FORTNITE)
    ok = validate_account(account, FORTNITE, previous=account)  # unchanged: kept
    assert ok.rank == Rank("Champion", None) and ok.region == "Old Region"
    with pytest.raises(ValidationError):  # switching to another invalid value is refused
        validate_account(replace(account, region="Other Old"), FORTNITE, previous=account)


def test_secret_extra_fields_never_searched() -> None:
    game = make_game("Fortnite", "blank")
    values = {CODE.id: "FAKECODE99", SKINS.id: "galaxy skin"}
    account = make_account(game, extra=tuple(sorted(values.items())))
    searchable = FORTNITE.searchable_field_ids
    assert filter_accounts([account], AccountFilter(text="galaxy"), searchable) == [account]
    assert filter_accounts([account], AccountFilter(text="FAKECODE99"), searchable) == []
    assert filter_accounts([account], AccountFilter(text="galaxy")) == []  # default: none


def test_account_repr_hides_extra_values() -> None:
    account = make_account(make_game(), extra=((CODE.id, "FAKECODE99"),))
    assert "FAKECODE99" not in repr(account)
