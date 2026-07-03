# -*- mode: python ; coding: utf-8 -*-
"""snp2le.spec - PyInstaller build recipe for a standalone snp2le executable.

Build (from the project root, with the venv active):

    pip install pyinstaller
    pyinstaller snp2le.spec

The result is dist/snp2le/snp2le(.exe) - a folder you can zip and share.  For a
single self-contained file instead of a folder, set ONEFILE = True below (larger,
slower first start, but one file).  See the README for details.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ONEFILE = False

# scikit-rf / schemdraw / matplotlib ship data files and have lazy imports that
# PyInstaller cannot see by static analysis, so collect them explicitly.
datas = []
datas += collect_data_files("skrf")
datas += collect_data_files("schemdraw")
datas += collect_data_files("matplotlib")
datas += [("snp2le/gui/assets", "snp2le/gui/assets")]   # logos (svg + png) + snp2le logo
datas += [("snp2le/examples", "snp2le/examples")]       # bundled Touchstone examples

hiddenimports = []
hiddenimports += collect_submodules("skrf")
hiddenimports += collect_submodules("scipy")
hiddenimports += collect_submodules("snp2le")            # follow dynamic structure imports

a = Analysis(
    ["snp2le/app.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6"],   # avoid clashing Qt bindings
    noarchive=False,
)
pyz = PYZ(a.pure)

# optional Windows icon (generate with: python tools/make_icon.py)
import os
_icon = "snp2le/gui/assets/snp2le.ico"
icon = _icon if os.path.exists(_icon) else None

if ONEFILE:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas, [],
        name="snp2le", console=False, icon=icon,
        upx=True, disable_windowed_traceback=False,
    )
else:
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name="snp2le", console=False, icon=icon,
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="snp2le")
