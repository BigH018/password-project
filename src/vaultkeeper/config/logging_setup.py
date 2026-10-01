"""Logging configuration with defense-in-depth redaction.

The primary rule is still: NEVER pass secrets or PII to a logger. The redaction filter and
the sanitized exception hooks only exist to limit damage if that rule is broken by mistake.

- Messages are scrubbed of anything that looks like an email, a ``name#tag`` ID or a
  ``password=...`` style pair.
- Exceptions are logged as type + stack locations only. Exception *messages* can contain
  user data, so they are never written.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

LOG_FILE_NAME = "vaultkeeper.log"
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3
REDACTED = "[REDACTED]"

_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_TAGGED_ID = re.compile(r"[^\s#]{1,64}#[A-Za-z0-9]{2,16}")
_SECRET_PAIR = re.compile(
    r"(?i)\b(password|passwd|pass|pwd|secret|totp|token|key)\b(\s*[:=]\s*)\S+"
)


def redact(text: str) -> str:
    """Replace email-like, ``name#tag``-like and ``password=value``-like substrings."""
    text = _SECRET_PAIR.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    text = _EMAIL.sub(REDACTED, text)
    return _TAGGED_ID.sub(REDACTED, text)


def format_exception_safely(
    exc_type: type[BaseException],
    exc: BaseException | None,
    tb: TracebackType | None,
) -> str:
    """Format an exception as its type chain and stack frames, WITHOUT any messages."""
    lines = ["Traceback (messages omitted):"]
    for frame in traceback.extract_tb(tb):
        lines.append(f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}')
    chain = [exc_type.__qualname__]
    cause = (exc.__cause__ or exc.__context__) if exc is not None else None
    while cause is not None and len(chain) < 10:
        chain.append(type(cause).__qualname__)
        cause = cause.__cause__ or cause.__context__
    lines.append(" <- ".join(chain))
    return "\n".join(lines)


class RedactionFilter(logging.Filter):
    """Scrub log records before they reach any handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = redact(record.getMessage())
        if record.exc_info and record.exc_info[0] is not None:
            exc_type, exc, tb = record.exc_info
            message = f"{message}\n{format_exception_safely(exc_type, exc, tb)}"
        record.msg = message
        record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def configure_logging(log_directory: Path | None, level: int = logging.INFO) -> logging.Logger:
    """Configure the root logger with redacting handlers and return it.

    Logs go to a rotating file in ``log_directory`` (if given) and to stderr when it exists
    (it may be None in a windowed PyInstaller build).
    """
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers: list[logging.Handler] = []
    if log_directory is not None:
        log_directory.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_directory / LOG_FILE_NAME,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        )
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler(sys.stderr))

    for handler in handlers:
        handler.addFilter(RedactionFilter())
        handler.setFormatter(formatter)
        root.addHandler(handler)
    return root


def install_exception_hooks(logger: logging.Logger) -> None:
    """Route uncaught exceptions (main and worker threads) to sanitized log entries."""

    def _hook(
        exc_type: type[BaseException],
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            return
        logger.critical("Uncaught exception\n%s", format_exception_safely(exc_type, exc, tb))

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        _hook(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
