"""Bootstrap: arguments, logging, settings, Qt application, services, lifecycle."""

from __future__ import annotations

import argparse
import atexit
import logging
import sys
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from vaultkeeper import demo
from vaultkeeper.config.constants import APP_NAME
from vaultkeeper.config.logging_setup import (
    close_logging,
    configure_logging,
    install_exception_hooks,
)
from vaultkeeper.config.paths import app_data_dir, log_dir, settings_path
from vaultkeeper.config.settings import load_settings, update_settings
from vaultkeeper.core.vault_service import VaultService
from vaultkeeper.ui.app_controller import AppController
from vaultkeeper.ui.qt_adapters import QtTaskRunner
from vaultkeeper.ui.theme import apply_dark_theme

log = logging.getLogger(__name__)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="vaultkeeper", description=f"{APP_NAME}")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="run with a throwaway vault of fake accounts in a temp folder (deleted on exit)",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    """Start the app and return its exit code."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    demo_env: demo.DemoEnv | None = None
    if args.demo:
        demo.sweep_stale_demo_dirs()
        demo_env = demo.create_demo_env()
        atexit.register(demo.cleanup_demo_env, demo_env)  # also on unexpected exit paths
        data_dir: Path = demo_env.data_dir
        if sys.stdout is not None:  # None in a windowed (no console) build
            print("VaultKeeper DEMO: fake data only, in a temp folder deleted on exit.")
            print(f"Demo master password: {demo.DEMO_PASSWORD}")
    else:
        data_dir = app_data_dir()

    logger = configure_logging(log_dir(data_dir))
    install_exception_hooks(logger)
    settings_file = settings_path(data_dir)
    settings = load_settings(settings_file)
    if demo_env is not None:  # demo backups go inside the demo folder too
        settings = update_settings(settings, vault_path=str(demo_env.vault_path),
                                   backup_dir=str(demo_env.root / "backups"))

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    apply_dark_theme(app)
    runner = QtTaskRunner()
    controller = AppController(
        settings,
        settings_file,
        runner,
        lambda path: VaultService(path, runner=runner),
        demo=demo_env is not None,
        new_vault_dir=demo_env.root if demo_env is not None else None,  # demo stays in temp
    )
    QTimer.singleShot(0, controller.start)
    try:
        return app.exec_()
    finally:
        if controller.service is not None:
            controller.service.lock()
        if demo_env is not None:
            close_logging()  # release the demo log file so the folder can be deleted
            if demo.cleanup_demo_env(demo_env) and sys.stdout is not None:
                print("VaultKeeper DEMO: temporary folder deleted.")
