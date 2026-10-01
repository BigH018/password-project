"""Demo environment: temp folder only, fake data only, deleted on cleanup."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import pytest

from conftest import FAST_KDF
from vaultkeeper import demo
from vaultkeeper.config.logging_setup import close_logging, configure_logging
from vaultkeeper.core.vault_service import VaultService


@pytest.fixture
def env(tmp_path: Path) -> demo.DemoEnv:
    return demo.create_demo_env(base=tmp_path, kdf_params=FAST_KDF)


def test_everything_lives_inside_one_demo_folder(env: demo.DemoEnv, tmp_path: Path) -> None:
    assert env.root.parent == tmp_path
    assert env.root.name.startswith(demo.DEMO_PREFIX)
    assert env.vault_path.parent == env.root
    assert env.data_dir.parent == env.root


def test_default_location_is_system_temp() -> None:
    """Without a base, the folder goes in the system temp dir (never the settings folder)."""
    created = demo.create_demo_env(kdf_params=FAST_KDF)
    try:
        assert created.root.parent == Path(tempfile.gettempdir())
    finally:
        demo.cleanup_demo_env(created)
    assert not created.root.exists()


def test_demo_vault_has_only_fake_data(env: demo.DemoEnv) -> None:
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock(demo.DEMO_PASSWORD)
    data = svc.data
    assert {g.name for g in data.games} == {"Valorant", "Marvel Rivals", "Overwatch",
                                           "Apex Legends"}
    assert len(data.accounts) == 30
    for account in data.accounts:
        assert account.email.endswith("@example.test")
        assert account.display_name.startswith("DemoAlt")
        assert account.password.startswith("Fake-Demo-Pass-")
    assert {a.status for a in data.accounts} == {"active", "banned", "locked", "retired"}


def test_cleanup_deletes_folder(env: demo.DemoEnv) -> None:
    assert demo.cleanup_demo_env(env) is True
    assert not env.root.exists()


def test_cleanup_refuses_non_demo_folder(tmp_path: Path) -> None:
    precious = tmp_path / "not-a-demo"
    precious.mkdir()
    fake_env = demo.DemoEnv(root=precious, data_dir=precious, vault_path=precious / "x.vault")
    with pytest.raises(ValueError):
        demo.cleanup_demo_env(fake_env)
    assert precious.exists()


def test_sweep_removes_only_demo_leftovers(tmp_path: Path) -> None:
    leftover = tmp_path / f"{demo.DEMO_PREFIX}old"
    leftover.mkdir()
    (leftover / "demo.vault").write_bytes(b"x")
    keep = tmp_path / "unrelated"
    keep.mkdir()
    demo.sweep_stale_demo_dirs(base=tmp_path)
    assert not leftover.exists() and keep.exists()


def test_cleanup_works_after_logging_to_demo_folder(env: demo.DemoEnv) -> None:
    """Regression: an open log file in the demo folder blocked deletion on Windows."""
    root_logger = logging.getLogger()
    saved = list(root_logger.handlers)
    try:
        logger = configure_logging(env.data_dir / "logs")
        logger.info("demo log line")
        close_logging()
        assert demo.cleanup_demo_env(env) is True
        assert not env.root.exists()
    finally:
        close_logging()
        for handler in saved:
            root_logger.addHandler(handler)


# --- the demo master password is simply "test" (user request, 2026-10-01) ---------------


def test_demo_password_is_test(env: demo.DemoEnv) -> None:
    assert demo.DEMO_PASSWORD == "test"
    svc = VaultService(env.vault_path, kdf_params=FAST_KDF)
    svc.unlock("test")
    assert svc.data.accounts  # the fake accounts are there


def test_real_vaults_still_need_a_strong_password(tmp_path: Path) -> None:
    from vaultkeeper.errors import WeakPasswordError

    with pytest.raises(WeakPasswordError):
        VaultService(tmp_path / "real.vault", kdf_params=FAST_KDF).create("test")
    assert not (tmp_path / "real.vault").exists()

