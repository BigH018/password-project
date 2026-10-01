"""Shared helpers for the vault_file tests (not a test module)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vaultkeeper.storage import vault_file as vf

OLD = b"old-vault-bytes"


NEW = b"new-vault-bytes"


def ok(_data: bytes) -> None:
    """Verifier that accepts anything."""


class SimulatedCrash(BaseException):
    """Stands in for a process being killed mid-save."""


@pytest.fixture
def existing(tmp_path: Path) -> Path:
    path = tmp_path / "v.vault"
    vf.write_vault_atomic(path, OLD, ok)
    return path


def leftovers(path: Path) -> list[Path]:
    return [p for p in (vf.tmp_path(path), path.with_name(path.name + ".bak.tmp")) if p.exists()]


# --- CR-H1 / SEC-Low8: quarantine mode never leaves the vault missing ----------------------


def quarantine_setup(existing: Path) -> Path:
    vf.write_vault_atomic(existing, b"second", ok)  # .bak = OLD (good), vault = "second"
    return vf.damaged_path(existing, "20260101-000000")
