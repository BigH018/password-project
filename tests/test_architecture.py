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
