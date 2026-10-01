# Vault file format (v1)

Reference spec for `crypto/`, `storage/vault_file.py` and `scripts/recover_vault.py`.
If you change anything here, update all three plus `tests/test_recover_script.py` in the same change.

## Layout

All integers are **big-endian** and unsigned. The file is `header || ciphertext_with_tag`.

| Offset | Size | Field           | Value / notes                                   |
|-------:|-----:|-----------------|-------------------------------------------------|
| 0      | 8    | magic           | `b"VKVAULT\x00"`                                |
| 8      | 2    | format_version  | `1`                                             |
| 10     | 1    | file_kind       | `1` = vault, `2` = export                       |
| 11     | 1    | kdf_id          | `1` = Argon2id (v1.3)                           |
| 12     | 4    | kdf_time_cost   | iterations                                      |
| 16     | 4    | kdf_memory_kib  | memory in KiB                                   |
| 20     | 1    | kdf_parallelism | lanes                                           |
| 21     | 1    | salt_len        | `16`                                            |
| 22     | 16   | salt            | `secrets.token_bytes(16)`                       |
| 38     | 1    | cipher_id       | `1` = AES-256-GCM                               |
| 39     | 1    | nonce_len       | `12`                                            |
| 40     | 12   | nonce           | fresh `secrets.token_bytes(12)` on every save   |
| 52     | 4    | ciphertext_len  | length of the ciphertext+tag that follows       |
| 56     | n    | ciphertext+tag  | AES-GCM output (16-byte tag appended)           |

- **AAD** = bytes `[0:56]` (the whole header). Any header change → `InvalidTag` → `VaultAuthError`.
- **Key**: see "Key derivation" below. It's derived once at unlock and kept as a `bytearray`
  only while unlocked. The salt stays the same between saves and changes on password change.
  The nonce changes on every save.
- An export (`file_kind=2`) uses the same layout, with its own password, salt and key.

## Key derivation (normative: every implementation must match exactly)

1. Take the master password as a Unicode string.
2. Normalize it to **Unicode NFC** (`unicodedata.normalize("NFC", password)`). No other
   changes: no trimming, no case folding.
3. Encode it as **UTF-8** bytes.
4. Run **Argon2id v1.3** with the header's salt, `time_cost`, `memory_kib` and `parallelism`,
   output length **32 bytes**. In Python: `argon2.low_level.hash_secret_raw(..., type=Type.ID)`.
5. Use those 32 bytes as the AES-256-GCM key.

NFC exists because the same visible password (e.g. `é`) can be typed as one code point or as
`e` plus a combining accent, depending on keyboard or IME. Without normalization the two would
derive different keys and the vault wouldn't open. `crypto/kdf.py` and
`scripts/recover_vault.py` both do this. Tests with an accented master password, created with
one form and opened with the other, cover the app (`test_vault_service.py`, `test_kdf.py`) and
the script (`test_recover_script.py`).

## Bounds (checked before the KDF runs)

| Field           | Allowed                          |
|-----------------|----------------------------------|
| magic           | exact match                      |
| format_version  | `1` (newer → refuse)             |
| file_kind       | `1` or `2`                       |
| kdf_id          | `1`                              |
| kdf_time_cost   | 1–10                             |
| kdf_memory_kib  | 8 MiB (8192) – 1 GiB (1048576)   |
| kdf_parallelism | 1–16                             |
| salt_len        | 16                               |
| cipher_id       | `1`                              |
| nonce_len       | 12                               |
| ciphertext_len  | ≥ 16 and == file size − 56       |

Violations raise `VaultFormatError`. That's safe to report, because it reveals nothing about the password.

## Payload

UTF-8 JSON:
```json
{
  "schema_version": 2,
  "games":    [{"id": "uuid", "name": "Valorant", "template": {
                  "tiers": [{"name": "Iron", "divisions": 3}],
                  "best_division_is_one": false, "roman_divisions": false,
                  "regions": ["NA", "EU"], "hidden_fields": [], "custom_fields": [
                    {"id": "uuid", "label": "Level", "kind": "number", "choices": []}]}}],
  "accounts": [{"id": "uuid", "game_id": "uuid", "extra": {"<field id>": "42"},
                "...": "see DATA_MODEL.md"}],
  "meta":     {"created_at": "ISO-8601 UTC", "updated_at": "ISO-8601 UTC"}
}
```
`format_version` covers the binary layout, and `schema_version` covers the JSON. Readers refuse
newer versions. Migrations live in `core/migrations.py` as `migrate_vN_to_vN+1`, each with tests
(`tests/test_migrations.py`, which includes opening a real encrypted v1 vault).

## KDF defaults and rationale

`time_cost=4`, `memory_kib=524288` (512 MiB), `parallelism=4`, 32-byte output.
- RFC 9106's low-memory recommendation is t=3, 64 MiB, p=4. OWASP's minimum is far lower
  (19 MiB). We use 8× the RFC memory and one more pass because this desktop app unlocks a few
  times a day on a machine with plenty of RAM, so each offline guess against a stolen vault
  costs much more.
- **Chosen so unlock stays under about 1 s on a modest PC.** Measured on the dev PC
  (2026-10-01): about 0.3 s for the KDF (the previous 256 MiB / t=3 took 0.10 s).
- The bounds (1 GiB, t ≤ 10) leave room to raise the defaults later. Params are stored per
  file, so old vaults keep working, and they pick up new defaults on the next password change.
- Argon2 runs through the injected `TaskRunner` (a worker thread in the UI), never on the UI thread.
- Tests inject tiny params (t=1, 8 MiB). One `@pytest.mark.slow` test uses the defaults.

## Atomic save procedure (`storage/vault_file.py`)

1. Write the new bytes to `<vault>.tmp` in the same directory, then `flush()` and `os.fsync()`.
2. **Verify:** read `<vault>.tmp` back, parse the header, decrypt with the current key, and parse
   the JSON payload. If anything fails, delete the tmp file, raise, and leave the vault untouched.
3. If `<vault>` exists: copy it to `<vault>.bak.tmp`, fsync, then `os.replace` it to `<vault>.bak`.
4. `os.replace(<vault>.tmp, <vault>)` (atomic within one volume on NTFS and POSIX).
5. On POSIX, fsync the directory. On startup, remove stale `.tmp` files left by earlier crashes.
6. If the main file fails to open, the UI *offers* to try `.bak`. It never switches silently.
7. **After opening from `.bak`**, the next save does NOT do step 3. Instead the current
   (damaged) main file is renamed to `<vault>.damaged-YYYYMMDD-HHMMSS` (`quarantine_as`), so
   the good `.bak` is never overwritten by a file that failed to open. Later saves go back to
   the normal rotation. Test: `test_save_after_opening_backup_keeps_good_bak_and_damaged_copy`.
   Enforced in core: `VaultService.unlock()` only reads `.bak` when called with
   `use_backup=True`, and `has_backup()` lets the UI decide whether to offer it
   (test: `test_damaged_vault_never_falls_back_to_backup`). The UI side gets a pytest-qt test
   in Phase 4.

Storage stays bytes-only. The verify callback (decrypt + parse) is injected by `vault_service`.

## Backups and exports

- **Backups** (`core/backup.py`) are byte-for-byte copies of the encrypted vault file,
  written atomically and compared with the source before they replace anything. They open
  with the same master password. Name: `<vault stem>-backup-YYYYMMDD-HHMMSS.vault`.
- **Exports** (`core/exporter.py`) are the same format with `file_kind = 2` and their own
  password, salt and key. They're decrypted and parsed before replacing anything. The app
  refuses to open an export as a vault (kind check). The recovery script reads both.

## Recovery script (`scripts/recover_vault.py`)

Standalone. Imports only the stdlib, `cryptography` and `argon2-cffi`, and never `vaultkeeper`.
Given a vault path, it prompts for the master password with `getpass` (or reads it from stdin
as UTF-8 with `--password-stdin`), applies the same NFC rule, and prints the decrypted
JSON to stdout. It applies the same bounds as above and contains no secrets. The user decides
where stdout goes, and the README warns that redirecting it to a file writes plaintext.

## Threading

`VaultService` splits slow operations into a pure *prepare* step (KDF + decrypt, safe on a
worker thread, touches no service state) and a *commit* step (updates state on the UI thread).
`*_async` methods send the prepare step through an injected `TaskRunner`.

## Required tests

- create → unlock round trip; wrong password → `VaultAuthError`
- flipping any single byte (header or ciphertext) → error; truncated file → `VaultFormatError`
- unknown version, kind, KDF or cipher id → `VaultFormatError`
- out-of-bounds KDF params rejected **before** the KDF runs (spy on the KDF)
- nonce differs on every save; salt changes on password change
- lock wipes key and data
- atomic save: an exception injected at each step leaves an openable vault; verify-after-write
  failure leaves the original untouched and no tmp file behind; `.bak` holds the previous version
- the recovery script decrypts a vault written by the app (run as a subprocess with list args)
