"""schematic_widget.py - render a CircuitIR's schematic (Schemdraw -> SVG ->
pixmap), scaled to fit the panel.  Falls back to a text note for the universal
macromodel, which has no human-readable schematic.
"""
from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtSvg import QSvgRenderer


class SchematicWidget(QtWidgets.QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setStyleSheet("QScrollArea, QWidget { background:#ffffff; }")
        self.label = QtWidgets.QLabel("schematic")
        self.label.setAlignment(QtCore.Qt.AlignCenter)
        self.label.setStyleSheet("color:#7d828c; background:#ffffff;")
        self.setWidget(self.label)
        self._svg = None

    def show_message(self, text):
        self._svg = None
        self.label.setPixmap(QtGui.QPixmap())
        self.label.setText(text)

    def show_drawing(self, drawing):
        self._svg = None
        if drawing is None:
            self.show_message("(no schematic)")
            return
        import matplotlib.pyplot as plt
        before = set(plt.get_fignums())
        try:
            svg = drawing.get_imagedata("svg")
            if isinstance(svg, str):
                svg = svg.encode("utf-8")
            self._svg = QtCore.QByteArray(svg)
        except Exception as exc:                    # noqa: BLE001
            self.show_message(f"(render failed: {exc})")
            return
        finally:
            for n in set(plt.get_fignums()) - before:
                plt.close(n)
        self._rescale()

    def _rescale(self):
        if self._svg is None:
            return
        renderer = QSvgRenderer(self._svg)
        size = renderer.defaultSize()
        if size.width() <= 0 or size.height() <= 0:
            return
        avail_w = max(self.viewport().width() - 12, 50)
        avail_h = max(self.viewport().height() - 12, 50)
        scale = min(avail_w / size.width(), avail_h / size.height())
        w = max(int(size.width() * scale), 1)
        h = max(int(size.height() * scale), 1)
        pix = QtGui.QPixmap(w, h); pix.fill(QtCore.Qt.transparent)
        p = QtGui.QPainter(pix); renderer.render(p); p.end()
        self.label.setPixmap(pix); self.label.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()
