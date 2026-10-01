"""Dark theme: bundled stylesheet loads, a missing one falls back to the palette."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from PyQt5.QtWidgets import QApplication

from vaultkeeper.ui import theme


@pytest.fixture
def restore_app_look(qapp: QApplication) -> Iterator[QApplication]:
    """Put the shared QApplication's look back so other tests are unaffected."""
    old_sheet, old_palette = qapp.styleSheet(), qapp.palette()
    yield qapp
    qapp.setStyleSheet(old_sheet)
    qapp.setPalette(old_palette)


def test_bundled_stylesheet_loads_and_is_plain_ascii() -> None:
    qss = theme.load_stylesheet()
    assert qss is not None
    assert "QPushButton" in qss and "QTableView" in qss
    assert qss.isascii()
    assert qss.count("{") == qss.count("}")


def test_stylesheet_uses_no_external_resources() -> None:
    qss = theme.load_stylesheet() or ""
    assert "url(" not in qss  # no images, nothing fetched: the app stays fully offline
    assert "http" not in qss


def test_apply_sets_style_palette_and_sheet(restore_app_look: QApplication) -> None:
    assert theme.apply_dark_theme(restore_app_look) is True
    assert "QPushButton" in restore_app_look.styleSheet()


def test_missing_stylesheet_falls_back_to_palette(
    restore_app_look: QApplication, caplog: Any
) -> None:
    caplog.set_level(logging.WARNING)
    assert theme.load_stylesheet("does-not-exist.qss") is None
    assert "Stylesheet unavailable" in caplog.text
    assert "does-not-exist" not in caplog.text  # no file names/paths in the log

    restore_app_look.setStyleSheet("")
    assert theme.apply_dark_theme(restore_app_look, stylesheet="") is False
    assert restore_app_look.styleSheet() == ""
    assert restore_app_look.palette().color(restore_app_look.palette().Window).name() == "#1f2227"


def test_shared_label_styles_still_exported() -> None:
    for style in (theme.ERROR_STYLE, theme.MUTED_STYLE, theme.WARNING_BANNER_STYLE):
        assert style.startswith(("color:", "background:"))
