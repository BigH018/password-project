"""Standalone VaultKeeper vault decryptor (emergency recovery).

Decrypts a VaultKeeper vault (format v1) with its master password and prints the JSON
contents to stdout. Needs only Python 3.11+, ``cryptography`` and ``argon2-cffi``. It does
NOT import the vaultkeeper package, so it works even if the app itself is broken.

This script contains no secrets. Its OUTPUT IS PLAINTEXT: everything in your vault,
including passwords. Redirecting it to a file writes your passwords to disk unencrypted.

Usage:
    python recover_vault.py path\\to\\my.vault            (prompts for the password)
    python recover_vault.py path\\to\\my.vault --password-stdin

Exit codes: 0 ok, 1 wrong password or damaged file, 2 not a valid vault / unsupported.

Format spec: docs/VAULT_FORMAT.md. Keep this file in sync with it.
"""

from __future__ import annotations

import argparse
import getpass
import json
import struct
import sys
import unicodedata
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"VKVAULT\x00"
HEADER = struct.Struct(">8sHBBIIBB16sBB12sI")  # 56 bytes, big-endian
MAX_FILE_BYTES = 64 * 1024 * 1024


class FormatProblem(Exception):
    """The file is not a vault this script understands."""


def parse_header(data: bytes) -> dict[str, object]:
    """Parse and bounds-check the v1 header BEFORE any expensive key derivation."""
    if len(data) < HEADER.size:
        raise FormatProblem("file too short")
    (magic, version, kind, kdf_id, t_cost, m_kib, par, salt_len, salt, cipher_id, nonce_len,
     nonce, ct_len) = HEADER.unpack_from(data)  # fmt: skip
    if magic != MAGIC:
        raise FormatProblem("not a VaultKeeper file")
    if version != 1:
        raise FormatProblem(f"unsupported format version {version}")
    if kind not in (1, 2) or kdf_id != 1 or cipher_id != 1:
        raise FormatProblem("unsupported file kind or algorithm")
    if salt_len != 16 or nonce_len != 12:
        raise FormatProblem("bad salt or nonce length")
    if not (1 <= t_cost <= 10 and 8192 <= m_kib <= 1048576 and 1 <= par <= 16):
        raise FormatProblem("key-derivation parameters out of range")
    if ct_len < 16 or ct_len != len(data) - HEADER.size:
        raise FormatProblem("file truncated or has extra data")
    return {"t": t_cost, "m": m_kib, "p": par, "salt": salt, "nonce": nonce}


def decrypt_vault(data: bytes, password: str) -> bytes:
    """Return the decrypted JSON bytes. Raises InvalidTag on a wrong password/damage."""
    hdr = parse_header(data)
    key = hash_secret_raw(
        secret=unicodedata.normalize("NFC", password).encode("utf-8"),
        salt=hdr["salt"],
        time_cost=hdr["t"],
        memory_cost=hdr["m"],
        parallelism=hdr["p"],
        hash_len=32,
        type=Type.ID,
    )
    return AESGCM(key).decrypt(hdr["nonce"], data[HEADER.size :], data[: HEADER.size])


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Decrypt a VaultKeeper vault to stdout.")
    parser.add_argument("vault", type=Path, help="path to the .vault file")
    parser.add_argument("--password-stdin", action="store_true",
                        help="read the master password from the first line of stdin")
    args = parser.parse_args(argv)

    try:
        if args.vault.stat().st_size > MAX_FILE_BYTES:
            print("Error: file is too large to be a vault.", file=sys.stderr)
            return 2
        data = args.vault.read_bytes()
    except OSError:
        print("Error: could not read the vault file.", file=sys.stderr)
        return 2

    if args.password_stdin:
        sys.stdin.reconfigure(encoding="utf-8")  # Windows pipes default to the ANSI codepage
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Master password: ")

    try:
        plaintext = decrypt_vault(data, password)
    except FormatProblem as exc:
        print(f"Error: not a valid vault ({exc}).", file=sys.stderr)
        return 2
    except InvalidTag:
        print("Error: wrong password or the vault file is damaged.", file=sys.stderr)
        return 1

    try:
        parsed = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        print("Error: decrypted, but the contents are not valid JSON.", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(parsed, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
