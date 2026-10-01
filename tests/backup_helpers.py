"""Shared helpers for the backup tests (not a test module)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import FAST_KDF, MASTER
from vaultkeeper.core.backup import BackupService
from vaultkeeper.core.vault_service import VaultService


class Clock:
    def __init__(self) -> None:
        self.now = 10_000.0
        self.n = 0

    def __call__(self) -> float:
        return self.now

    def stamp(self) -> str:
        self.n += 1
        return f"20260101-0000{self.n:02d}"


@pytest.fixture
def vault(tmp_path: Path) -> VaultService:
    svc = VaultService(tmp_path / "main" / "my.vault", kdf_params=FAST_KDF)
    svc.create(MASTER)
    return svc


@pytest.fixture
def clock() -> Clock:
    return Clock()


def service(vault: VaultService, tmp_path: Path, clock: Clock, keep: int = 10,
             interval: int = 10) -> BackupService:
    return BackupService(vault.path, tmp_path / "backups", keep, interval, clock, clock.stamp)
