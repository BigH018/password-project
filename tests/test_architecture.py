"""Static checks that enforce CLAUDE.md architecture and security rules on src/ and scripts/."""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "vaultkeeper"
SCRIPTS = ROOT / "scripts"
MAX_LINES = 300

# Which vaultkeeper packages each layer may import. None = unrestricted (top-level wiring).
ALLOWED_INTERNAL: dict[str, set[str] | None] = {
    "errors": set(),
    "config": {"config", "errors"},
    "crypto": {"crypto", "config", "errors"},
    "storage": {"storage", "config", "errors"},
    "security": {"security", "config", "errors"},
    "core": {"core", "crypto", "storage", "config", "errors"},
    "ui": {"ui", "core", "security", "config", "errors"},
    "demo": {"core", "crypto", "config", "errors"},
    "app": None,
    "main": None,
    "__main__": None,
    "__init__": None,
}
QT_ALLOWED_LAYERS = {"ui", "app"}
QT_MODULES = ("PyQt5", "PyQt6", "PySide2", "PySide6", "sip")

FORBIDDEN_MODULES = (
    "random", "pickle", "cPickle", "marshal", "shelve", "socket", "ssl", "http", "urllib.request",
    "urllib3", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "poplib", "imaplib",
    "telnetlib", "xmlrpc", "asyncio", "subprocess", "webbrowser", "PyQt5.QtNetwork",
    "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebEngineCore", "yaml",
)  # fmt: skip
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_ATTR_CALLS = {("os", "system"), ("os", "popen")}


def _python_files(base: Path) -> list[Path]:
    return sorted(base.rglob("*.py")) if base.exists() else []


def _layer(path: Path) -> str:
    rel = path.relative_to(SRC)
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def _imported_modules(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
            names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _matches(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


SRC_FILES = _python_files(SRC)
ALL_FILES = SRC_FILES + _python_files(SCRIPTS)


def _id(path: Path) -> str:
    return str(path.relative_to(ROOT))


def test_source_files_found() -> None:
    assert SRC_FILES, "no source files discovered"


@pytest.mark.parametrize("path", SRC_FILES, ids=_id)
def test_layer_dependencies(path: Path) -> None:
    layer = _layer(path)
    assert layer in ALLOWED_INTERNAL, f"unknown layer {layer!r}: add it to ALLOWED_INTERNAL"
    allowed = ALLOWED_INTERNAL[layer]
    for module in _imported_modules(_parse(path)):
        if any(_matches(module, qt) for qt in QT_MODULES):
            assert layer in QT_ALLOWED_LAYERS, f"{layer} must not import Qt ({module})"
        if allowed is not None and _matches(module, "vaultkeeper"):
            parts = module.split(".")
            if len(parts) > 1:
                target = parts[1]
                assert target in allowed, f"{layer} must not import vaultkeeper.{target}"


@pytest.mark.parametrize("path", ALL_FILES, ids=_id)
def test_no_forbidden_imports(path: Path) -> None:
    for module in _imported_modules(_parse(path)):
        for bad in FORBIDDEN_MODULES:
            assert not _matches(module, bad), f"forbidden import {module}"


@pytest.mark.parametrize("path", ALL_FILES, ids=_id)
def test_no_forbidden_calls(path: Path) -> None:
    for node in ast.walk(_parse(path)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            assert func.id not in FORBIDDEN_CALLS, f"forbidden call {func.id}()"
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            assert (func.value.id, func.attr) not in FORBIDDEN_ATTR_CALLS
        for kw in node.keywords:
            is_true = isinstance(kw.value, ast.Constant) and kw.value.value is True
            assert not (kw.arg == "shell" and is_true), "shell=True is forbidden"


@pytest.mark.parametrize("path", _python_files(SCRIPTS), ids=_id)
def test_scripts_are_standalone(path: Path) -> None:
    for module in _imported_modules(_parse(path)):
        assert not _matches(module, "vaultkeeper"), "scripts must not import vaultkeeper"


@pytest.mark.parametrize("path", ALL_FILES, ids=_id)
def test_no_bare_except(path: Path) -> None:
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ExceptHandler):
            assert node.type is not None, f"bare except at line {node.lineno}"


TEST_FILES = sorted((ROOT / "tests").rglob("*.py"))


@pytest.mark.parametrize("path", ALL_FILES + TEST_FILES, ids=_id)
def test_source_is_ascii_only(path: Path) -> None:
    """Non-ASCII must be written as escapes (blocks invisible bidi/"Trojan Source" chars)."""
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        bad = [hex(ord(ch)) for ch in line if ord(ch) > 126 or (ord(ch) < 32 and ch != "\t")]
        assert not bad, f"line {lineno} has raw non-ASCII/control characters {bad}"


def test_flag_large_files() -> None:
    """Files over MAX_LINES are flagged (warning, not failure) for splitting."""
    for path in ALL_FILES:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > MAX_LINES:
            warnings.warn(f"{_id(path)} has {lines} lines; consider splitting", stacklevel=1)


# --- SEC-H1: no user data rendered as HTML --------------------------------------------------
# Qt's AutoText renders HTML-looking text (an account named "<img src=//host/x>" would load a
# remote image). Labels and message boxes are only built in ui/safe_text.py, which sets
# Qt.PlainText; text that Qt turns into a label by itself must be a fixed literal.
UI_DIR = SRC / "ui"
SAFE_TEXT = UI_DIR / "safe_text.py"
RICH_TEXT_WIDGETS = {"QLabel", "QMessageBox"}
STATIC_BOXES = {"critical", "warning", "information", "question", "about"}
FIXED_TEXT_ONLY = {"setToolTip", "setStatusTip", "setWhatsThis", "link_label"}


def _is_fixed_text(node: ast.expr) -> bool:
    """A string literal or an UPPER_CASE module constant: never user data."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    return isinstance(node, ast.Name) and node.id.isupper()


def _rich_text_risks(tree: ast.AST) -> list[str]:
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        owner = func.value.id if (isinstance(func, ast.Attribute)
                                  and isinstance(func.value, ast.Name)) else ""
        where = f"line {node.lineno}"
        if name in RICH_TEXT_WIDGETS:
            problems.append(f"{where}: {name}() - use safe_text.plain_label/message_box")
        if owner == "QMessageBox" and name in STATIC_BOXES:
            problems.append(f"{where}: QMessageBox.{name}() - use safe_text.message_box")
        if name in FIXED_TEXT_ONLY and node.args and not _is_fixed_text(node.args[0]):
            problems.append(f"{where}: {name}() needs fixed text")
        if name == "addRow" and len(node.args) >= 2:
            first = node.args[0]
            is_plain = (isinstance(first, ast.Call) and isinstance(first.func, ast.Name)
                        and first.func.id == "plain_label")
            if not (is_plain or _is_fixed_text(first)):
                problems.append(f"{where}: addRow(text, ...) needs fixed text or plain_label()")
    return problems


UI_FILES = [p for p in _python_files(UI_DIR) if p != SAFE_TEXT]


@pytest.mark.parametrize("path", UI_FILES, ids=_id)
def test_ui_never_renders_user_text_as_html(path: Path) -> None:
    assert _rich_text_risks(_parse(path)) == []


def test_rich_text_check_catches_risky_code() -> None:
    risky = (
        "a = QLabel(name)\n"
        "b = QtWidgets.QLabel(self)\n"
        "QMessageBox.critical(None, 't', text)\n"
        "box = QMessageBox()\n"
        "w.setToolTip(account.notes)\n"
        "form.addRow(custom.label, widget)\n"
        "link_label(f'{name}', self)\n"
    )
    assert len(_rich_text_risks(ast.parse(risky))) == 7
    safe = (
        "a = plain_label(name, self)\n"
        "w.setToolTip('Fixed help')\n"
        "form.addRow('Name', widget)\n"
        "form.addRow(plain_label(custom.label, self), widget)\n"
        "form.addRow(self.extra_box)\n"
        "link_label(BACKUPS_OFF, self)\n"
    )
    assert _rich_text_risks(ast.parse(safe)) == []


def test_safe_text_sets_plain_format() -> None:
    source = SAFE_TEXT.read_text(encoding="utf-8")
    assert source.count("setTextFormat(Qt.PlainText)") >= 2
