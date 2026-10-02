"""Encrypted export: own password, export file kind, path rules, recovery script reads it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from conftest import FAST_KDF, MASTER, OTHER_MASTER
from fake_data import make_vault
from vaultkeeper.core.exporter import check_export_path, write_export
from vaultkeeper.core.models import SCHEMA_VERSION
from vaultkeeper.core.serialization import dumps_payload, loads_payload
from vaultkeeper.crypto import envelope
from vaultkeeper.crypto.header import FileKind
from vaultkeeper.errors import ValidationError, VaultAuthError, VaultFormatError, WeakPasswordError

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "recover_vault.py"


def test_export_round_trip_with_its_own_password(tmp_path: Path) -> None:
    data = make_vault()
    target = tmp_path / "export.vault"
    write_export(dumps_payload(data), target, OTHER_MASTER, kdf_params=FAST_KDF)
    raw = target.read_bytes()
    assert b"Fake-Passw0rd" not in raw and b"example.test" not in raw
    hdr, _key, plaintext = envelope.open_with_password(raw, OTHER_MASTER, FileKind.EXPORT)
    assert hdr.file_kind is FileKind.EXPORT
    assert loads_payload(plaintext) == data
    with pytest.raises(VaultAuthError):
        envelope.open_with_password(raw, MASTER)


def test_export_is_not_openable_as_a_vault(tmp_path: Path) -> None:
    target = tmp_path / "export.vault"
    write_export(dumps_payload(make_vault()), target, OTHER_MASTER, kdf_params=FAST_KDF)
    with pytest.raises(VaultFormatError):
        envelope.open_with_password(target.read_bytes(), OTHER_MASTER, FileKind.VAULT)


def test_export_password_policy(tmp_path: Path) -> None:
    with pytest.raises(WeakPasswordError):
        write_export(b"{}", tmp_path / "x.vault", "short", kdf_params=FAST_KDF)
    assert not (tmp_path / "x.vault").exists()


def test_export_path_rules(tmp_path: Path) -> None:
    vault = tmp_path / "my.vault"
    assert check_export_path(tmp_path / "out", vault).name == "out.vault"
    assert check_export_path(tmp_path / "my.vault.bak", vault).name == "my.vault.bak.vault"
    with pytest.raises(ValidationError, match="vault file itself"):
        check_export_path(vault, vault, overwrite=True)
    existing = tmp_path / "old.vault"
    existing.write_bytes(b"x")
    with pytest.raises(ValidationError, match="already exists"):
        check_export_path(existing, vault)
    assert check_export_path(existing, vault, overwrite=True) == existing


def test_recovery_script_reads_exports(tmp_path: Path) -> None:
    target = tmp_path / "export.vault"
    write_export(dumps_payload(make_vault()), target, OTHER_MASTER, kdf_params=FAST_KDF)
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(SCRIPT), str(target), "--password-stdin"],
        input=OTHER_MASTER + "\n", capture_output=True, text=True, encoding="utf-8",
        timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert f'"schema_version": {SCHEMA_VERSION}' in result.stdout


def test_cancelled_export_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / "export.vault"
    assert write_export(b"{}", target, OTHER_MASTER, kdf_params=FAST_KDF,
                        cancelled=lambda: True) is False
    assert not target.exists()


# --- CR-L3: full paths only, folder errors are friendly --------------------------------


def test_export_path_must_be_a_full_path(tmp_path: Path) -> None:
    with pytest.raises(ValidationError) as info:
        check_export_path(Path("relative-export"), tmp_path / "v.vault")
    assert info.value.field == "export_file" and "full path" in info.value.reason


def test_unreadable_export_folder_is_a_friendly_error(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from vaultkeeper.errors import VaultIOError

    def denied(_self: Path) -> bool:
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "exists", denied)
    with pytest.raises(VaultIOError):
        check_export_path(tmp_path / "locked" / "export", tmp_path / "v.vault")

