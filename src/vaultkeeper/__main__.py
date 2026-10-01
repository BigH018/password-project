"""Allow ``python -m vaultkeeper``."""

from vaultkeeper.main import main

if __name__ == "__main__":
    raise SystemExit(main())
