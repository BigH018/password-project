"""Game setup layout: Ranks / Fields and regions tabs, live counts, toggles, preview."""

from __future__ import annotations

from typing import Any

import pytest

from conftest import FakeStore
from fake_data import tiny_png
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.game_template import GameTemplate, TierDef
from vaultkeeper.ui import game_setup_dialog as gs
from vaultkeeper.ui.widgets.field_toggles import FieldToggles
from vaultkeeper.ui.widgets.ladder_editor import LadderEditor


@pytest.fixture
def dialog(qtbot: Any, store: FakeStore) -> gs.GameSetupDialog:
    dlg = gs.GameSetupDialog(GameService(store))
    qtbot.addWidget(dlg)
    return dlg


def _titles(dialog: gs.GameSetupDialog) -> list[str]:
    tabs = [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
    return [*tabs, dialog.regions_box.title(), dialog.extras_box.title()]


def test_tabs_and_boxes_show_live_counts(dialog: gs.GameSetupDialog) -> None:
    assert _titles(dialog) == [
        "Ranks (0)", "Fields and regions", "Regions (0)", "Extra fields (0)"]
    dialog.ladder.add_tier("Bronze", 3)
    dialog.ladder.add_tier("Silver", 3)
    dialog.regions.setPlainText("EU\n\n  \nNA")
    dialog.extras.add_field(None)
    assert _titles(dialog) == [
        "Ranks (2)", "Fields and regions", "Regions (2)", "Extra fields (1)"]
    dialog.ladder.table.selectRow(0)
    dialog.ladder.remove_button.click()
    assert _titles(dialog)[0] == "Ranks (1)"


def test_regions_sit_in_the_fields_tab(dialog: gs.GameSetupDialog) -> None:
    fields_page = dialog.tabs.widget(gs.FIELDS_TAB)
    assert dialog.tabs.count() == 2
    assert fields_page.isAncestorOf(dialog.regions) and fields_page.isAncestorOf(dialog.extras)


def test_starter_updates_the_counts(dialog: gs.GameSetupDialog) -> None:
    dialog.starter.setCurrentIndex(dialog.starter.findData("valorant"))
    dialog.starter_button.click()
    assert _titles(dialog)[0] == "Ranks (9)" and _titles(dialog)[2] == "Regions (6)"


def test_field_toggles_load_and_read_back(qtbot: Any) -> None:
    toggles = FieldToggles()
    qtbot.addWidget(toggles)
    toggles.load(GameTemplate(hidden_fields=frozenset({"tag", "rank"})))
    assert not toggles.boxes["tag"].isChecked() and toggles.boxes["region"].isChecked()
    toggles.boxes["region"].setChecked(False)
    assert toggles.hidden() == {"tag", "rank", "region"}


def test_rank_actions_need_a_selected_rank_and_preview_follows(qtbot: Any) -> None:
    ladder = LadderEditor()
    qtbot.addWidget(ladder)
    ladder.load(GameTemplate(tiers=(TierDef("Iron", 3, tiny_png()), TierDef("Radiant"))))
    ladder.table.setCurrentCell(-1, -1)
    assert not ladder.remove_button.isEnabled() and not ladder.picture_button.isEnabled()
    ladder.table.selectRow(0)
    assert ladder.picture_button.isEnabled() and ladder.remove_picture_button.isEnabled()
    assert ladder.preview.pixmap() is not None and not ladder.preview.pixmap().isNull()
    ladder.table.selectRow(1)
    assert not ladder.remove_picture_button.isEnabled() and ladder.preview.text() == "none"
