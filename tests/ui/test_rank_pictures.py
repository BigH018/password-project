"""Rank pictures in Game setup: file -> small PNG, set/remove per rank, add-rank form, save."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage

from conftest import FakeStore
from fake_data import tiny_png
from vaultkeeper.core.game_service import GameService
from vaultkeeper.core.game_template import GameTemplate, TierDef
from vaultkeeper.core.rank_image import MAX_SIDE, is_valid_rank_image
from vaultkeeper.ui import game_setup_dialog as gs
from vaultkeeper.ui import messages, rank_pictures
from vaultkeeper.ui.widgets.add_rank_dialog import AddRankDialog
from vaultkeeper.ui.widgets.ladder_editor import LadderEditor


def _image_file(path: Path, width: int, height: int, fmt: str) -> Path:
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.red)
    assert image.save(str(path), fmt)
    return path


def _size(data: bytes | None) -> tuple[int, int]:
    image = QImage.fromData(data or b"", "PNG")
    return image.width(), image.height()


# --- file -> stored picture -----------------------------------------------------------------


def test_big_png_is_shrunk_keeping_its_shape(qapp: Any, tmp_path: Path) -> None:
    data = rank_pictures.picture_from_file(_image_file(tmp_path / "a.png", 200, 100, "PNG"))
    assert is_valid_rank_image(data) and _size(data) == (MAX_SIDE, MAX_SIDE // 2)


def test_small_png_keeps_its_size(qapp: Any, tmp_path: Path) -> None:
    path = tmp_path / "small.png"
    path.write_bytes(tiny_png(4, 4))
    assert _size(rank_pictures.picture_from_file(path)) == (4, 4)


def test_ico_uses_its_largest_frame(qapp: Any, tmp_path: Path) -> None:
    app_icon = Path(rank_pictures.__file__).parent / "assets" / "app_icon.ico"  # 16-256 px
    data = rank_pictures.picture_from_file(app_icon)
    assert is_valid_rank_image(data) and _size(data) == (MAX_SIDE, MAX_SIDE)
    single = rank_pictures.picture_from_file(_image_file(tmp_path / "r.ico", 32, 32, "ICO"))
    assert _size(single) == (32, 32)


def test_unusable_files_give_none(qapp: Any, tmp_path: Path) -> None:
    text = tmp_path / "notes.png"
    text.write_text("not a picture", encoding="utf-8")
    bmp = _image_file(tmp_path / "bitmap.png", 8, 8, "BMP")  # other formats refused
    huge = tmp_path / "huge.png"
    huge.write_bytes(tiny_png() + bytes(rank_pictures.MAX_SOURCE_BYTES))
    for path in (text, bmp, huge, tmp_path / "missing.png", tmp_path):
        assert rank_pictures.picture_from_file(path) is None


def test_icon_for_stored_picture(qapp: Any) -> None:
    assert not rank_pictures.picture_icon(tiny_png()).isNull()
    assert rank_pictures.picture_icon(None).isNull()


# --- choosing a picture ---------------------------------------------------------------------


@pytest.fixture
def picks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """The image picker returns ``state["path"]`` and records the start folder; errors too."""
    good = tmp_path / "pics" / "gold.png"
    good.parent.mkdir()
    good.write_bytes(tiny_png(8, 8))
    state: dict[str, Any] = {"path": str(good), "starts": [], "errors": []}

    def fake_choose(_parent: Any, _title: str, start: str) -> str:
        state["starts"].append(start)
        return state["path"]

    monkeypatch.setattr(rank_pictures, "choose_image_file", fake_choose)
    monkeypatch.setattr(messages, "show_error",
                        lambda _p, title, text: state["errors"].append((title, text)))
    return state


@pytest.fixture
def ladder(qtbot: Any) -> LadderEditor:
    editor = LadderEditor()
    qtbot.addWidget(editor)
    editor.load(GameTemplate(tiers=(TierDef("Iron", 3), TierDef("Radiant"))))
    return editor


def test_set_and_remove_a_rank_picture(ladder: LadderEditor, picks: dict[str, Any]) -> None:
    ladder.table.selectRow(1)
    ladder.picture_button.click()
    iron, radiant = ladder.tiers()
    assert iron.image is None and _size(radiant.image) == (8, 8)
    assert not ladder.table.item(1, 0).icon().isNull()
    ladder.remove_picture_button.click()
    assert ladder.tiers()[1].image is None and ladder.table.item(1, 0).icon().isNull()


def test_picture_follows_rename_and_reorder(ladder: LadderEditor,
                                            picks: dict[str, Any]) -> None:
    ladder.table.selectRow(0)
    ladder.picture_button.click()
    ladder.table.item(0, 0).setText("Iron+")
    ladder.down_button.click()
    assert [(t.name, t.image is not None) for t in ladder.tiers()] == [
        ("Radiant", False), ("Iron+", True)]


def test_picker_remembers_the_folder(ladder: LadderEditor, picks: dict[str, Any]) -> None:
    ladder.table.selectRow(0)
    ladder.picture_button.click()
    ladder.table.selectRow(1)
    ladder.picture_button.click()
    assert picks["starts"] == ["", str(Path(picks["path"]).parent)]


def test_bad_or_cancelled_pick_changes_nothing(ladder: LadderEditor, picks: dict[str, Any],
                                               tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_text("not a picture", encoding="utf-8")
    ladder.table.selectRow(0)
    picks["path"] = str(bad)
    ladder.picture_button.click()
    assert len(picks["errors"]) == 1 and ".ico or .png" in picks["errors"][0][1]
    picks["path"] = ""  # cancelled
    ladder.picture_button.click()
    assert len(picks["errors"]) == 1
    assert all(t.image is None for t in ladder.tiers())


def test_no_selected_rank_does_nothing(ladder: LadderEditor, picks: dict[str, Any]) -> None:
    ladder.table.setCurrentCell(-1, -1)
    ladder.picture_button.click()
    assert picks["starts"] == [] and all(t.image is None for t in ladder.tiers())


def test_add_rank_form_takes_an_optional_picture(qtbot: Any, picks: dict[str, Any]) -> None:
    added: list[tuple[str, int, bytes | None]] = []
    dialog = AddRankDialog(lambda *args: added.append(args), [], rank_pictures.PicturePicker())
    qtbot.addWidget(dialog)
    dialog.name.setText("Gold")
    dialog.picture_button.click()
    assert dialog.picture_preview.pixmap() is not None
    dialog.add_button.click()
    dialog.name.setText("Platinum")
    dialog.add_button.click()  # the picture is per rank: cleared after each add
    assert [(n, d, _size(i) if i else None) for n, d, i in added] == [
        ("Gold", 0, (8, 8)), ("Platinum", 0, None)]


def test_game_setup_saves_pictures_and_counts_them_as_changes(
        qtbot: Any, store: FakeStore, picks: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch) -> None:
    games = GameService(store)
    game = games.add("Fake Valorant", GameTemplate(tiers=(TierDef("Gold", 3),)))
    dialog = gs.GameSetupDialog(games)
    qtbot.addWidget(dialog)
    for row in range(dialog.list.count()):
        if dialog.list.item(row).data(Qt.UserRole) == game.id:
            dialog.list.setCurrentRow(row)
    assert not dialog.has_changes
    dialog.ladder.table.selectRow(0)
    dialog.ladder.picture_button.click()
    assert dialog.has_changes
    dialog.save_button.click()
    assert _size(games.get(game.id).template.tiers[0].image) == (8, 8)
    assert not dialog.has_changes
