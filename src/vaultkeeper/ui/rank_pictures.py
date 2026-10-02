"""Rank pictures in the UI: a picked .ico/.png file -> small PNG bytes, and PNG -> icon.

Core only checks the stored bytes (``core/rank_image.py``). Decoding and shrinking need Qt,
so they live here. Only PNG and ICO files are decoded, at most ``MAX_SOURCE_BYTES`` big.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PyQt5.QtGui import QIcon, QImage, QImageReader, QPixmap
from PyQt5.QtWidgets import QWidget

from vaultkeeper.core.rank_image import MAX_SIDE, is_valid_rank_image
from vaultkeeper.ui import messages
from vaultkeeper.ui.file_pickers import choose_image_file

MAX_SOURCE_BYTES = 5 * 1024 * 1024
MAX_SOURCE_SIDE = 4096
_FORMATS = (b"png", b"ico")
UNUSABLE_TEXT = ("That file can't be used as a rank picture. Choose an .ico or .png image "
                 "(at most 5 MB).")


def _largest_frame(reader: QImageReader) -> QImage:
    """An .ico file holds several sizes: keep the biggest (a .png has just one)."""
    best = QImage()
    for index in range(max(reader.imageCount(), 1)):
        if index and not reader.jumpToImage(index):
            break
        size = reader.size()
        if size.width() > MAX_SOURCE_SIDE or size.height() > MAX_SOURCE_SIDE:
            continue  # never decode huge frames
        frame = reader.read()
        if frame.width() * frame.height() > best.width() * best.height():
            best = frame
    return best


def _png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def picture_from_file(path: Path) -> bytes | None:
    """The picture shrunk to fit ``MAX_SIDE`` px each way, as PNG bytes; None if unusable."""
    if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
        return None
    reader = QImageReader(str(path))
    reader.setDecideFormatFromContent(True)
    if bytes(reader.format()) not in _FORMATS:
        return None
    image = _largest_frame(reader)
    if image.isNull():
        return None
    if image.width() > MAX_SIDE or image.height() > MAX_SIDE:
        image = image.scaled(MAX_SIDE, MAX_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    data = _png_bytes(image.convertToFormat(QImage.Format_ARGB32))
    return data if is_valid_rank_image(data) else None


def picture_pixmap(data: bytes | None) -> QPixmap:
    """A stored picture as a pixmap (null if there is none)."""
    pixmap = QPixmap()
    if data is not None:
        pixmap.loadFromData(QByteArray(data), "PNG")
    return pixmap


def picture_icon(data: bytes | None) -> QIcon:
    """A stored picture as an icon (null if there is none)."""
    pixmap = picture_pixmap(data)
    return QIcon() if pixmap.isNull() else QIcon(pixmap)


class PicturePicker:
    """Asks for an .ico/.png file and shrinks it. Remembers the folder for the next rank."""

    def __init__(self) -> None:
        self.folder = ""

    def choose(self, parent: QWidget | None) -> bytes | None:
        """The chosen picture, or None if cancelled or unusable (the user is told)."""
        path = choose_image_file(parent, "Choose a rank picture", self.folder)
        if not path:
            return None
        self.folder = str(Path(path).parent)
        try:
            data = picture_from_file(Path(path))
        except OSError:
            data = None  # unreadable file: same message as any unusable one
        if data is None:
            messages.show_error(parent, "Rank picture", UNUSABLE_TEXT)
        return data
