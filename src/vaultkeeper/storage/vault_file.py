"""Atomic, verified writes of vault bytes, with the previous version kept as ``.bak``.

Procedure (docs/VAULT_FORMAT.md):
1. write ``<vault>.tmp``, flush, fsync
2. read the tmp file back and run the injected ``verify`` callback (decrypt + parse)
3. copy the current vault to ``<vault>.bak`` (via ``.bak.tmp`` + fsync + replace), or after
   opening from ``.bak``, copy it to ``<vault>.damaged-...`` instead (``.bak`` untouched)
4. ``os.replace(<vault>.tmp, <vault>)``, then fsync the directory (POSIX)

The main file is only ever COPIED, never moved, so there is always a file at ``<vault>``:
a crash or error at any step leaves either the old or the new vault intact. This module
only handles bytes: it knows nothing about keys or accounts.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import sys
import time
from collections.abc import Callable
from pathlib import Path, PurePath, PureWindowsPath

from vaultkeeper.errors import VaultFormatError, VaultIOError, VaultKeeperError

MAX_VAULT_BYTES = 64 * 1024 * 1024
REPLACE_RETRIES = 5
REPLACE_RETRY_DELAY = 0.05  # seconds; Windows can briefly lock files (antivirus, indexer)

Verifier = Callable[[bytes], None]
# Temp files are always NEW files: O_EXCL never opens (or writes through) anything that is
# already there, such as a planted symlink (SEC-Low7). O_NOFOLLOW where the OS has it.
_NEW_FILE = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
             | getattr(os, "O_NOFOLLOW", 0))


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
    """Write ``data`` to a NEW temp file (a leftover is removed first) and fsync it."""
    _remove_quietly(path)  # unlinking a symlink removes the link, never its target
    fd = os.open(path, _NEW_FILE, 0o600)
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
    _remove_quietly(staging)
    _copy_to_new_file(path, staging)  # exclusive create + fsync
    _replace(staging, backup_path(path))


def _copy_to_new_file(src: Path, dst: Path) -> None:
    """Copy ``src`` to a NEW file ``dst`` and fsync it. Never overwrites an existing file."""
    with open(src, "rb") as source, open(dst, "xb") as target:  # "x": exclusive create
        try:
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
        except OSError:
            target.close()
            _remove_quietly(dst)
            raise


def write_vault_atomic(
    path: Path, data: bytes, verify: Verifier, *, quarantine_as: Path | None = None
) -> None:
    """Write ``data`` to ``path`` atomically, verifying it on disk before replacing.

    ``verify`` gets the bytes read back from the temp file and must raise a
    VaultKeeperError if they don't decrypt and parse. On any failure, the existing vault is
    untouched and the temp file is removed.

    Normally the current file is copied to ``.bak``. With ``quarantine_as`` (used after
    opening from ``.bak`` because the main file failed), the current file is copied to that
    NEW path instead and ``.bak`` is NOT touched, so a damaged file never replaces the good
    backup. The main file is never moved: if the final replace fails, it is still there
    (and the quarantine copy is removed again).
    """
    tmp = tmp_path(path)
    quarantined: Path | None = None
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
            _copy_to_new_file(path, quarantine_as)
            quarantined = quarantine_as
        _replace(tmp, path)
        quarantined = None  # the new vault is in place: the damaged copy must stay
        _fsync_dir(path.parent)
    except OSError as exc:
        _undo_failed_write(path, quarantined)
        raise VaultIOError("Could not save the vault file.") from exc
    except BaseException:
        _undo_failed_write(path, quarantined)
        raise


def _undo_failed_write(path: Path, quarantined: Path | None) -> None:
    """Remove what a failed save created. The main file was never moved, so it is intact."""
    _remove_quietly(tmp_path(path))
    _remove_quietly(_backup_tmp_path(path))
    if quarantined is not None:
        _remove_quietly(quarantined)


def _public_folder() -> Path | None:
    public = os.environ.get("PUBLIC")  # the shared Public folder on Windows
    return Path(public) if public else None


def folder_may_be_shared(
    path: Path,
    platform: str = sys.platform,
    public: Path | None = None,
    mode_of: Callable[[Path], int] = lambda p: p.stat().st_mode,
) -> bool:
    """Heuristic (SEC-Low7): could other users of this PC change files in the vault's folder?

    Windows: a drive root or a folder directly below it (e.g. ``C:\\Vaults``, which by default
    lets every signed-in user create and change files; a USB stick often has no permissions at
    all), or the shared Public folder. Folders inside a user profile are private by default.
    Elsewhere: the folder is group- or world-writable. Used for a warning only, never to block.
    """
    if platform == "win32":
        folder: PurePath = PureWindowsPath(str(path)).parent
        anchor = PureWindowsPath(folder.anchor)
        shared_public = public if public is not None else _public_folder()
        in_public = shared_public is not None and folder.is_relative_to(
            PureWindowsPath(str(shared_public)))
        return folder == anchor or folder.parent == anchor or in_public
    try:
        mode = mode_of(path.parent)
    except OSError:
        return False
    return bool(mode & (stat.S_IWGRP | stat.S_IWOTH))


def cleanup_stale_temp_files(path: Path) -> None:
    """Remove temp files left behind by an earlier crash (never touches vault or .bak)."""
    _remove_quietly(tmp_path(path))
    _remove_quietly(_backup_tmp_path(path))


def copy_file_verified(source: Path, target: Path) -> None:
    """Copy ``source`` to ``target`` atomically (tmp + fsync + replace) and verify the bytes.

    Used for backups: the vault file is already encrypted, so this never sees plaintext.
    """
    data = read_vault_bytes(source)

    def same_bytes(written: bytes) -> None:
        if written != data:
            raise VaultFormatError("Backup copy does not match the vault file.")

    write_bytes_atomic(target, data, same_bytes)


def write_bytes_atomic(path: Path, data: bytes, verify: Verifier) -> None:
    """Atomic write (tmp + fsync + verify + replace) without keeping a .bak."""
    tmp = tmp_path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_and_sync(tmp, data)
        try:
            verify(tmp.read_bytes())
        except VaultKeeperError as exc:
            raise VaultIOError("The written file failed verification; nothing was changed.") \
                from exc
        _replace(tmp, path)
        _fsync_dir(path.parent)
    except OSError as exc:
        _remove_quietly(tmp)
        raise VaultIOError("Could not write the file.") from exc
    except BaseException:
        _remove_quietly(tmp)
        raise
