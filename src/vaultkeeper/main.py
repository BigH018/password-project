"""Entry point only. All bootstrapping lives in ``vaultkeeper.app``."""

from __future__ import annotations


def main() -> int:
    """Start the application and return the process exit code."""
    from vaultkeeper.app import run  # deferred so importing main stays cheap

    return run()


if __name__ == "__main__":
    raise SystemExit(main())
