"""test_qt_essentials.py - guard the PySide6-Essentials-only dependency.

snp2le declares `PySide6-Essentials`, not the full `PySide6` metapackage, so the
GUI must never touch a module that ships in PySide6-Addons (QtWebEngine,
QtCharts, QtMultimedia, ...).  A stray import would still run on a developer
machine that has the metapackage installed and only break on an
Essentials-only deployment such as the IIC-OSIC-TOOLS image, so it is worth a
test.  Run with:  pytest -q

This is a source scan, not an import test: it needs no display and no Qt.
"""
import ast
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Modules shipped in the PySide6-Essentials wheel (6.6 .. 6.11).  Anything else
# under the PySide6 namespace comes from PySide6-Addons.
ESSENTIALS = {
    "QtCore", "QtGui", "QtWidgets", "QtNetwork", "QtConcurrent", "QtDBus",
    "QtDesigner", "QtHelp", "QtOpenGL", "QtOpenGLWidgets", "QtPrintSupport",
    "QtQml", "QtQuick", "QtQuickControls2", "QtQuickTest", "QtQuickWidgets",
    "QtSql", "QtSvg", "QtSvgWidgets", "QtTest", "QtUiTools", "QtXml",
}


def _qt_submodules(path):
    """Every PySide6 submodule referenced by `path`, at any nesting depth."""
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    found = set()
    for node in ast.walk(tree):
        # from PySide6.QtSvg import QSvgRenderer  /  from PySide6 import QtCore
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "PySide6":
                found.update(a.name for a in node.names)
            elif node.module.startswith("PySide6."):
                found.add(node.module.split(".")[1])
        # import PySide6.QtCharts
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("PySide6."):
                    found.add(a.name.split(".")[1])
    return found


def test_no_pyside6_addons_imports():
    offenders = {}
    for py in (ROOT / "snp2le").rglob("*.py"):
        extra = _qt_submodules(py) - ESSENTIALS
        if extra:
            offenders[str(py.relative_to(ROOT))] = sorted(extra)
    assert not offenders, (
        "PySide6-Addons modules imported; snp2le depends on "
        f"PySide6-Essentials only: {offenders}")


def test_dependency_declares_essentials():
    """pyproject must not regress to the full PySide6 metapackage."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps = text.split("dependencies = [", 1)[1].split("]", 1)[0]
    lines = [ln.strip() for ln in deps.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    qt = [ln for ln in lines if "PySide6" in ln]
    assert qt, "no PySide6 dependency found in pyproject.toml"
    assert all("PySide6-Essentials" in ln for ln in qt), (
        f"pyproject.toml must depend on PySide6-Essentials, got: {qt}")
