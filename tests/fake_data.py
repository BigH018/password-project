"""Obviously fake games and accounts for tests and demos. NEVER put real data here."""

from __future__ import annotations

import struct
import zlib
from typing import Any

from vaultkeeper.core.game_template import starter_template
from vaultkeeper.core.models import Account, Game, Rank, VaultData, new_id, utc_now_iso
from vaultkeeper.core.rank_image import PNG_SIGNATURE

FAKE_PASSWORD = "Fake-Passw0rd-1!"


def _png_chunk(kind: bytes, body: bytes) -> bytes:
    crc = zlib.crc32(kind + body)
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def tiny_png(width: int = 4, height: int = 4) -> bytes:
    """A real (decodable) solid red RGBA PNG, built with the standard library only."""
    row = bytes((0,)) + bytes((255, 0, 0, 255)) * width  # filter byte + pixels
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (PNG_SIGNATURE + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", zlib.compress(row * height)) + _png_chunk(b"IEND", b""))


def make_game(name: str = "Valorant", preset: str = "valorant") -> Game:
    """Return a fake game whose template starts from ``preset`` ("custom"/"blank" = blank)."""
    return Game(id=new_id(), name=name, template=starter_template(preset))


def make_account(game: Game, n: int = 1, **overrides: Any) -> Account:
    """Return a fake, valid account for ``game``. ``n`` varies the identifying fields."""
    now = utc_now_iso()
    values: dict[str, Any] = {
        "id": new_id(),
        "game_id": game.id,
        "display_name": f"FakePlayer{n}",
        "tag": "TEST",
        "login_username": f"fake_login_{n}",
        "password": FAKE_PASSWORD,
        "email": f"player{n}@example.test",
        "email_password": None,
        "email_login_url": "https://mail.example.test/login",
        "region": "EU",
        "rank": Rank("Platinum", 2),
        "status": "active",
        "recovery_email": f"recovery{n}@example.test",
        "totp_secret": None,
        "tags": ("main-alt", "demo"),
        "notes": "Fake account for tests.\nSecond line.",
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return Account(**values)


def make_vault(accounts_per_game: int = 2) -> VaultData:
    """Return a fake vault with three games and a few accounts each."""
    data = VaultData.empty()
    regions = {"valorant": "EU", "marvel_rivals": "EU", "overwatch": "Europe"}
    ranks = {
        "valorant": Rank("Gold", 3),
        "marvel_rivals": Rank("Diamond", 1),
        "overwatch": Rank("Master", 4),
    }
    for name, preset in (("Valorant", "valorant"), ("Marvel Rivals", "marvel_rivals"),
                         ("Overwatch", "overwatch")):
        game = make_game(name, preset)
        data.games.append(game)
        for i in range(accounts_per_game):
            data.accounts.append(
                make_account(game, n=i, region=regions[preset], rank=ranks[preset])
            )
    return data
