"""The standalone recovery script decrypts vaults written by the app."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from conftest import MASTER
from fake_data import make_account, make_game
from vaultkeeper.core.models import SCHEMA_VERSION
from vaultkeeper.core.vault_service import VaultService

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "recover_vault.py"


def _run(vault: Path, password: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argv list, no shell
        [sys.executable, str(SCRIPT), str(vault), "--password-stdin"],
        input=password + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def _make_vault(make_service: Callable[..., VaultService]) -> VaultService:
    svc = make_service()
    svc.create(MASTER)
    game = make_game("Overwatch", "overwatch")
    svc.data.games.append(game)
    svc.data.accounts.append(make_account(game, display_name="Recover\u00e9", region="Europe"))
    svc.save()
    return svc


def test_script_decrypts_app_vault(make_service: Callable[..., VaultService],
                                   vault_path: Path) -> None:
    svc = _make_vault(make_service)
    result = _run(vault_path, MASTER)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["games"][0]["name"] == "Overwatch"
    assert payload["games"][0]["template"]["tiers"][0] == {"name": "Bronze", "divisions": 5,
                                                           "image": None}
    assert payload["accounts"][0]["display_name"] == "Recover\u00e9"
    assert payload["accounts"][0]["password"] == svc.data.accounts[0].password


def test_script_non_ascii_master_password_nfc(make_service: Callable[..., VaultService],
                                              vault_path: Path) -> None:
    """App creates with composed form; script opens with decomposed form (and vice versa)."""
    composed = "caf\u00e9 cr\u00e8me fake passphrase \u00fc\u00df"
    decomposed = "cafe\u0301 cre\u0300me fake passphrase u\u0308\u00df"
    make_service().create(composed)
    for password in (composed, decomposed):
        result = _run(vault_path, password)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["schema_version"] == SCHEMA_VERSION


def test_script_wrong_password(make_service: Callable[..., VaultService],
                               vault_path: Path) -> None:
    _make_vault(make_service)
    result = _run(vault_path, "wrong fake passphrase")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "wrong password" in result.stderr.lower()


def test_script_rejects_non_vault(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.vault"
    bogus.write_bytes(b"not a vault at all" * 10)
    result = _run(bogus, MASTER)
    assert result.returncode == 2 and result.stdout == ""


def test_script_out_of_bounds_header(make_service: Callable[..., VaultService],
                                     vault_path: Path) -> None:
    _make_vault(make_service)
    raw = bytearray(vault_path.read_bytes())
    raw[16:20] = (4 * 1024 * 1024).to_bytes(4, "big")
    vault_path.write_bytes(bytes(raw))
    result = _run(vault_path, MASTER)
    assert result.returncode == 2
    assert "out of range" in result.stderr
