# VaultKeeper

A local-only, offline desktop password manager built around game accounts (Valorant, Marvel
Rivals, Overwatch and more). Everything is stored in one encrypted vault file on your PC.

> **Status:** in development (Phase 1 of 8). The app is not usable yet.
> **Do not enter real accounts until backups work (end of Phase 5).**

## Install and run (Windows)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .
pytest                 # run the tests
python -m vaultkeeper  # run the app (UI arrives in Phase 4)
```

## Security notes

- **A lost master password means a lost vault.** There is no reset, no recovery question and
  no back door. Write your master password down and keep it somewhere safe and offline.
- The app makes no network calls. Your data never leaves the vault file and the backup folder
  you choose.
- The vault uses Argon2id key derivation and AES-256-GCM authenticated encryption, from the
  `argon2-cffi` and `cryptography` libraries. Any tampering with the file is detected.
- Python cannot guarantee that decrypted data is wiped from memory. Locking drops all
  references, but copies may stay in RAM until it is reused.
- `scripts/recover_vault.py` (Phase 2) is a small standalone script that decrypts a vault with
  your master password and prints the contents. It contains no secrets. Its output is
  **plaintext**, so don't redirect it to a file unless you mean to.
- Once all your accounts are in the vault, delete your old plaintext text files.

See `docs/VAULT_FORMAT.md` for the file format and `CLAUDE.md` for development rules.
