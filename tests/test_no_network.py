"""The network block works, and every app module imports cleanly with it active."""

from __future__ import annotations

import importlib
import pkgutil
import socket

import pytest

import vaultkeeper
from conftest import NetworkBlockedError


def test_socket_connect_is_blocked() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        with pytest.raises(NetworkBlockedError):
            sock.connect(("192.0.2.1", 80))  # TEST-NET-1, never routable


def test_dns_is_blocked() -> None:
    with pytest.raises(NetworkBlockedError):
        socket.getaddrinfo("example.test", 80)


def test_all_modules_import_offline() -> None:
    names = [m.name for m in pkgutil.walk_packages(vaultkeeper.__path__, "vaultkeeper.")]
    assert names
    for name in names:
        importlib.import_module(name)
