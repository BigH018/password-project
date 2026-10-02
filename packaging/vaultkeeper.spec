# PyInstaller spec for Account Manager (VaultKeeper). Decided with the user (2026-10-02):
# one-folder builds, no UPX, no admin rights, file details from vaultkeeper.__version__.
# One Analysis, two programs:
#   "Account Manager"            windowed (no console): the one to pin
#   "Account Manager (console)"  same app with a console window, for troubleshooting only
#
# Build (from the repo root, venv active):
#   pyinstaller packaging/vaultkeeper.spec --noconfirm --clean --distpath <output folder>
# Each program lands in <output folder>/<name>/ with its .exe and an _internal folder.

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is defined by PyInstaller
SRC = ROOT / "src"
ICON = str(SRC / "vaultkeeper" / "ui" / "assets" / "app_icon.ico")
APP_NAME = "Account Manager"
CONSOLE_NAME = "Account Manager (console)"

init_text = (SRC / "vaultkeeper" / "__init__.py").read_text(encoding="utf-8")
VERSION = re.search(r'__version__ = "([0-9.]+)"', init_text).group(1)
numbers = tuple(int(n) for n in (VERSION.split(".") + ["0", "0", "0"])[:4])


def version_info(exe_name: str) -> VSVersionInfo:
    """The details shown in the .exe's Properties -> Details tab."""
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
        kids=[
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "BigH"),
                StringStruct("FileDescription", "Account Manager - offline password manager"),
                StringStruct("FileVersion", VERSION),
                StringStruct("InternalName", "vaultkeeper"),
                StringStruct("LegalCopyright", "Copyright (c) BigH. MIT License."),
                StringStruct("OriginalFilename", f"{exe_name}.exe"),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ],
    )


a = Analysis(  # noqa: F821
    [str(SRC / "vaultkeeper" / "__main__.py")],
    pathex=[str(SRC)],
    # The dark theme and the app icon are read with importlib.resources at runtime.
    datas=collect_data_files("vaultkeeper", includes=["ui/styles/*.qss", "ui/assets/*.ico"]),
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821


def program(name: str, console: bool) -> None:
    exe = EXE(  # noqa: F821
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        icon=ICON,
        version=version_info(name),
        console=console,
        upx=False,
        uac_admin=False,
    )
    COLLECT(exe, a.binaries, a.datas, name=name, upx=False)  # noqa: F821


program(APP_NAME, console=False)
program(CONSOLE_NAME, console=True)
