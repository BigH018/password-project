"""Redaction filter and sanitized exception logging (defense in depth)."""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from vaultkeeper.config import logging_setup as ls


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    hook, thread_hook = sys.excepthook, threading.excepthook
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)
    sys.excepthook = hook
    threading.excepthook = thread_hook


@pytest.mark.parametrize(
    ("text", "leaked"),
    [
        ("user player1@example.test logged", "player1@example.test"),
        ("riot id FakePlayer#TEST", "FakePlayer#TEST"),
        ("password=Fake-Passw0rd-1!", "Fake-Passw0rd-1!"),
        ("Secret: JBSWY3DPEHPK3PXP", "JBSWY3DPEHPK3PXP"),
    ],
)
def test_redact(text: str, leaked: str) -> None:
    out = ls.redact(text)
    assert leaked not in out
    assert ls.REDACTED in out


def test_redact_leaves_normal_text() -> None:
    assert ls.redact("account updated id=1234") == "account updated id=1234"


def test_log_file_is_redacted_and_exceptions_have_no_message(
    tmp_path: Path, restore_logging: None
) -> None:
    logger = ls.configure_logging(tmp_path, logging.DEBUG)
    logger.info("copied for %s", "player9@example.test")
    try:
        raise ValueError("Fake-Passw0rd-1! leaked into an exception message")
    except ValueError:
        logger.exception("operation failed")
    for h in logger.handlers:
        h.flush()
    content = (tmp_path / ls.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "player9@example.test" not in content
    assert "Fake-Passw0rd-1!" not in content
    assert "ValueError" in content
    assert "operation failed" in content


def test_excepthook_logs_type_not_message(tmp_path: Path, restore_logging: None) -> None:
    logger = ls.configure_logging(tmp_path, logging.INFO)
    ls.install_exception_hooks(logger)
    try:
        raise KeyError("player1@example.test")
    except KeyError:
        sys.excepthook(*sys.exc_info())
    for h in logger.handlers:
        h.flush()
    content = (tmp_path / ls.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "KeyError" in content
    assert "player1@example.test" not in content


def test_format_exception_safely_includes_chain() -> None:
    try:
        try:
            raise OSError("inner detail")
        except OSError as inner:
            raise RuntimeError("outer detail") from inner
    except RuntimeError as exc:
        text = ls.format_exception_safely(type(exc), exc, exc.__traceback__)
    assert "RuntimeError <- OSError" in text
    assert "detail" not in text


def _raise_fake() -> None:
    raise RuntimeError("player1@example.test Fake-Passw0rd-1!")


def test_on_error_called_after_logging_without_details(
    tmp_path: Path, restore_logging: None
) -> None:
    logger = ls.configure_logging(tmp_path)
    calls: list[tuple[object, ...]] = []
    ls.install_exception_hooks(logger, lambda *args: calls.append(args))
    try:
        _raise_fake()
    except RuntimeError:
        sys.excepthook(*sys.exc_info())
    assert calls == [()]  # the notifier gets nothing: no exception, no message
    ls.close_logging()
    assert "RuntimeError" in (tmp_path / ls.LOG_FILE_NAME).read_text(encoding="utf-8")


def test_failing_on_error_is_logged_and_swallowed(tmp_path: Path, restore_logging: None) -> None:
    logger = ls.configure_logging(tmp_path)

    def broken() -> None:
        raise ValueError("Fake-Passw0rd-1!")

    ls.install_exception_hooks(logger, broken)
    try:
        _raise_fake()
    except RuntimeError:
        sys.excepthook(*sys.exc_info())  # must not raise
    ls.close_logging()
    text = (tmp_path / ls.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "Error notice failed (ValueError)" in text
    assert "Fake-Passw0rd" not in text


def test_thread_exceptions_also_notify(tmp_path: Path, restore_logging: None) -> None:
    logger = ls.configure_logging(tmp_path)
    calls: list[bool] = []
    ls.install_exception_hooks(logger, lambda: calls.append(True))
    worker = threading.Thread(target=_raise_fake)
    worker.start()
    worker.join()
    ls.close_logging()
    assert calls == [True]

