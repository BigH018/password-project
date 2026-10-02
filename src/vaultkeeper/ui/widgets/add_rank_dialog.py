"""Quick "add rank" form: name, divisions (yes/no, how many), optional picture. Repeats."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.game_template import MAX_DIVISIONS
from vaultkeeper.ui.rank_pictures import PicturePicker, picture_pixmap
from vaultkeeper.ui.safe_text import plain_label
from vaultkeeper.ui.theme import ERROR_STYLE, MUTED_STYLE

PREVIEW_SIZE = 32


class AddRankDialog(QDialog):
    """Calls ``on_add(name, divisions, image)`` per rank; Enter adds and clears for the next.

    The divisions choice is kept between ranks, since most ranks in a game share it. The
    picture is per rank, so it is cleared after each add.
    """

    def __init__(self, on_add: Callable[[str, int, bytes | None], None], existing: list[str],
                 pictures: PicturePicker | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_add = on_add
        self._pictures = pictures or PicturePicker()
        self._image: bytes | None = None
        self._existing = {name.casefold() for name in existing}
        self.added = 0
        self.setWindowTitle("Add ranks")
        self.setMinimumWidth(360)

        self.name = QLineEdit(self)
        self.name.setPlaceholderText("e.g. Bronze")
        self.has_divisions = QCheckBox("This rank has divisions (like Bronze 1, 2, 3)", self)
        self.count = QSpinBox(self)
        self.count.setRange(1, MAX_DIVISIONS)
        self.count.setValue(3)
        self.count.setEnabled(False)
        self.picture_button = QPushButton("Choose...", self)
        self.picture_button.setAutoDefault(False)  # Enter still adds the rank
        self.picture_preview = plain_label(parent=self)
        self.picture_preview.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        hint = plain_label(
            "Add ranks from lowest to highest. Press Enter to add the next one.", self)
        hint.setStyleSheet(MUTED_STYLE)
        hint.setWordWrap(True)
        self.error_label = plain_label(parent=self)
        self.error_label.setStyleSheet(ERROR_STYLE)
        self.add_button = QPushButton("Add", self)
        self.add_button.setDefault(True)
        self.done_button = QPushButton("Done", self)

        form = QFormLayout()
        form.addRow("Rank name", self.name)
        form.addRow("", self.has_divisions)
        form.addRow("How many?", self.count)
        picture_row = QHBoxLayout()
        picture_row.addWidget(self.picture_button)
        picture_row.addWidget(self.picture_preview)
        picture_row.addStretch(1)
        form.addRow("Picture (optional)", picture_row)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.done_button)
        buttons.addWidget(self.add_button)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self.has_divisions.toggled.connect(self.count.setEnabled)
        self.picture_button.clicked.connect(self._choose_picture)
        self.add_button.clicked.connect(self._add)
        self.name.returnPressed.connect(self._add)
        self.done_button.clicked.connect(self.accept)
        self.name.setFocus()

    def _choose_picture(self) -> None:
        image = self._pictures.choose(self)
        if image is not None:
            self._show_picture(image)

    def _show_picture(self, image: bytes | None) -> None:
        self._image = image
        pixmap = picture_pixmap(image)
        if not pixmap.isNull():
            pixmap = pixmap.scaled(PREVIEW_SIZE, PREVIEW_SIZE, Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
        self.picture_preview.setPixmap(pixmap)

    def _add(self) -> None:
        name = self.name.text().strip()
        if not name:
            self.error_label.setText("Type a rank name.")
            return
        if name.casefold() in self._existing:
            self.error_label.setText("That rank is already in the list.")
            return
        divisions = self.count.value() if self.has_divisions.isChecked() else 0
        self._on_add(name, divisions, self._image)
        self._existing.add(name.casefold())
        self.added += 1
        self.error_label.clear()
        self.name.clear()
        self._show_picture(None)
        self.name.setFocus()
