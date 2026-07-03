"""logo.py - load the snp2le logo (S-parameter dip -> lumped network) from SVG,
for the title bar and the window/taskbar icon.
"""
from __future__ import annotations
import os
from PySide6 import QtCore, QtGui
from PySide6.QtSvg import QSvgRenderer

_SVG = os.path.join(os.path.dirname(__file__), "assets", "snp2le_logo.svg")


def _renderer():
    if os.path.exists(_SVG):
        with open(_SVG, "rb") as fh:
            return QSvgRenderer(QtCore.QByteArray(fh.read()))
    return None


def logo_pixmap(size: int = 26) -> QtGui.QPixmap:
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)
    r = _renderer()
    if r is not None:
        p = QtGui.QPainter(pix)
        r.render(p)
        p.end()
    return pix


def logo_icon() -> QtGui.QIcon:
    icon = QtGui.QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(s))
    return icon


def svg_pixmap(path: str, height: int) -> QtGui.QPixmap:
    """Render an SVG file to a pixmap scaled to `height`, preserving aspect."""
    if not os.path.exists(path):
        return QtGui.QPixmap()
    with open(path, "rb") as fh:
        r = QSvgRenderer(QtCore.QByteArray(fh.read()))
    size = r.defaultSize()
    if size.height() <= 0:
        return QtGui.QPixmap()
    width = max(1, int(size.width() * height / size.height()))
    pix = QtGui.QPixmap(width, height)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    r.render(p)
    p.end()
    return pix
