"""Atomic, verified writes of vault bytes, with the previous version kept as ``.bak``.

Procedure (docs/VAULT_FORMAT.md):
1. write ``<vault>.tmp``, flush, fsync
2. read the tmp file back and run the injected ``verify`` callback (decrypt + parse)
3. copy the current vault to ``<vault>.bak`` (via ``.bak.tmp`` + fsync + replace)
4. ``os.replace(<vault>.tmp, <vault>)``, then fsync the directory (POSIX)

A crash or error at any step leaves either the old or the new vault intact. This module
only handles bytes: it knows nothing about keys or accounts.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path

from vaultkeeper.errors import VaultFormatError, VaultIOError, VaultKeeperError

MAX_VAULT_BYTES = 64 * 1024 * 1024
REPLACE_RETRIES = 5
REPLACE_RETRY_DELAY = 0.05  # seconds; Windows can briefly lock files (antivirus, indexer)

Verifier = Callable[[bytes], None]


def tmp_path(path: Path) -> Path:
    """Temp file used while writing ``path``."""
    return path.with_name(path.name + ".tmp")


def backup_path(path: Path) -> Path:
    """Previous-version backup kept next to ``path``."""
    return path.with_name(path.name + ".bak")


def damaged_path(path: Path, stamp: str | None = None) -> Path:
    """An unused ``<vault>.damaged-YYYYMMDD-HHMMSS[-N]`` name next to ``path``."""
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}.damaged-{stamp}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.damaged-{stamp}-{counter}")
        counter += 1
    return candidate


def _backup_tmp_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak.tmp")


def read_vault_bytes(path: Path) -> bytes:
    """Read a vault (or backup/export) file, refusing absurdly large files."""
    try:
        size = path.stat().st_size
        if size > MAX_VAULT_BYTES:
            raise VaultFormatError("File is too large to be a vault.")
        return path.read_bytes()
    except FileNotFoundError:
        raise VaultIOError("Vault file not found.") from None
    except OSError as exc:
        raise VaultIOError("Could not read the vault file.") from exc


def _write_and_sync(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def _replace(src: Path, dst: Path) -> None:
    for attempt in range(REPLACE_RETRIES):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_RETRIES - 1:
                raise
            time.sleep(REPLACE_RETRY_DELAY)


def _fsync_dir(directory: Path) -> None:
    if sys.platform == "win32":
        return  # not supported on Windows; NTFS metadata journaling covers the rename
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove_quietly(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _keep_previous_version(path: Path) -> None:
    if not path.exists():
        return
    staging = _backup_tmp_path(path)
    shutil.copyfile(path, staging)
    with open(staging, "rb+") as fh:
        os.fsync(fh.fileno())
    _replace(staging, backup_path(path))


def write_vault_atomic(
    path: Path, data: bytes, verify: Verifier, *, quarantine_as: Path | None = None
) -> None:
    """Write ``data`` to ``path`` atomically, verifying it on disk before replacing.

    ``verify`` gets the bytes read back from the temp file and must raise a
    VaultKeeperError if they don't decrypt and parse. On any failure, the existing vault is
    untouched and the temp file is removed.

    Normally the current file becomes ``.bak``. With ``quarantine_as`` (used after opening
    from ``.bak`` because the main file failed), the current file is renamed to that path
    instead, and ``.bak`` is NOT touched, so a damaged file never replaces the good backup.
    """
    tmp = tmp_path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_and_sync(tmp, data)
        try:
            verify(tmp.read_bytes())
        except VaultKeeperError as exc:
            raise VaultIOError("The written vault failed verification; nothing was changed.") \
                from exc
        if quarantine_as is None:
            _keep_previous_version(path)
        elif path.exists():
            _replace(path, quarantine_as)
        _replace(tmp, path)
        _fsync_dir(path.parent)
    except OSError as exc:
        _remove_quietly(tmp)
        _remove_quietly(_backup_tmp_path(path))
        raise VaultIOError("Could not save the vault file.") from exc
    except BaseException:
        _remove_quietly(tmp)
        _remove_quietly(_backup_tmp_path(path))
        raise


def cleanup_stale_temp_files(path: Path) -> None:
    """Remove temp files left behind by an earlier crash (never touches vault or .bak)."""
    _remove_quietly(tmp_path(path))
    _remove_quietly(_backup_tmp_path(path))
