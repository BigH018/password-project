"""Entry point only. All bootstrapping lives in ``vaultkeeper.app`` (Phase 4)."""

from __future__ import annotations

import sys


def main() -> int:
    """Start the application and return the process exit code."""
    # The UI and app bootstrap arrive in Phase 4.
    print("VaultKeeper: the user interface is not built yet (Phase 4).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
