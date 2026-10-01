"""Shared fixtures. The network block is autouse: any network attempt fails the test."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

from fake_data import make_vault
from vaultkeeper.core.models import VaultData


class NetworkBlockedError(RuntimeError):
    """Raised when code under test tries to use the network."""


def _blocked(*_args: Any, **_kwargs: Any) -> Any:
    raise NetworkBlockedError("Network access is forbidden in VaultKeeper tests.")


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make every outbound connection or DNS lookup raise."""
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    yield


@pytest.fixture
def fake_vault() -> VaultData:
    """A small vault of obviously fake data."""
    return make_vault()
