"""Obviously fake games and accounts for tests and demos. NEVER put real data here."""

from __future__ import annotations

from typing import Any

from vaultkeeper.core.models import Account, Game, Rank, VaultData, new_id, utc_now_iso

FAKE_PASSWORD = "Fake-Passw0rd-1!"


def make_game(name: str = "Valorant", preset: str = "valorant") -> Game:
    """Return a fake game."""
    return Game(id=new_id(), name=name, preset=preset)


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
