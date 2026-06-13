"""footer.py - light footer bar: JKU logo (left), IICQC logo (centre) and the
copyright (right), matching the filter designer.

Logos are pre-rasterised PNGs (transparent background, black artwork) loaded with
QPixmap - reliable across platforms, unlike rendering the Inkscape SVGs through
QtSvg.  Regenerate them from the SVGs with tools/make_logos.py if they change.
"""
from __future__ import annotations
import os
from PySide6 import QtCore, QtGui, QtWidgets

_ASSETS = os.path.join(os.path.dirname(__file__), "assets")


def _png(name, height):
    pm = QtGui.QPixmap(os.path.join(_ASSETS, name))
    if pm.isNull():
        return QtGui.QPixmap()
    return pm.scaledToHeight(height, QtCore.Qt.SmoothTransformation)


class Footer(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("footer")
        self.setFixedHeight(52)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(18, 8, 18, 8); lay.setSpacing(10)

        jku = QtWidgets.QLabel(); jku.setPixmap(_png("jku.png", 34))
        lay.addWidget(jku)
        lay.addStretch(1)

        iicqc = QtWidgets.QLabel(); iicqc.setPixmap(_png("iicqc.png", 26))
        lay.addWidget(iicqc)
        lay.addStretch(1)

        cr = QtWidgets.QLabel("\u00a9 Simon Dorrer")
        cr.setObjectName("footerText")
        lay.addWidget(cr)
