"""top_bar.py - control strip.

Dark title bar: snp2le logo + title, then (right) View selector + Help.
Light controls row: Load .sNp, Mode (Universal / Structure), Structure, PDK, Max
order, Enforce passivity.  Structures that do not match the loaded port count, and
PDKs that are not supported yet, are greyed out so an invalid choice can never be
made.
"""
from __future__ import annotations
import math
from PySide6 import QtCore, QtGui, QtWidgets

from core.structures import structure_items
from core.pdk import pdk_items, DEFAULT_PDK, excluded_structures
from .style import JKU_BLUE

_DISABLED_GREY = QtGui.QColor("#9aa0aa")


def _reset_icon(color=JKU_BLUE):
    """A circular-arrow 'reset' QIcon: a near-closed ring with a clear arrowhead."""
    pm = QtGui.QPixmap(32, 32); pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    col = QtGui.QColor(color)
    cx, cy, r = 16, 16, 9.0
    pen = QtGui.QPen(col, 2.6); pen.setCapStyle(QtCore.Qt.RoundCap)
    p.setPen(pen)
    start_deg, span_deg = 120, 305       # near-closed ring, small gap at the top
    p.drawArc(QtCore.QRectF(cx - r, cy - r, 2 * r, 2 * r),
              int(start_deg * 16), int(span_deg * 16))
    # arrowhead at the arc end, oriented along the (counter-clockwise) tangent
    end = math.radians(start_deg + span_deg)
    ex, ey = cx + r * math.cos(end), cy - r * math.sin(end)
    tx, ty = -math.sin(end), -math.cos(end)     # unit tangent (direction of travel)
    nx, ny = math.cos(end), -math.sin(end)      # unit radial (arrow half-width)
    half_len, half_w = 3.25, 4.2
    tip = (ex + tx * half_len, ey + ty * half_len)
    base = (ex - tx * half_len, ey - ty * half_len)
    p.setPen(QtCore.Qt.NoPen); p.setBrush(col)
    path = QtGui.QPainterPath()
    path.moveTo(*tip)
    path.lineTo(base[0] + nx * half_w, base[1] + ny * half_w)
    path.lineTo(base[0] - nx * half_w, base[1] - ny * half_w)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QtGui.QIcon(pm)


def _set_item_enabled(combo, index, enabled):
    item = combo.model().item(index)
    if item is not None:
        item.setEnabled(enabled)
        # also grey the text so an unavailable entry reads as disabled
        item.setForeground(QtGui.QBrush() if enabled
                           else QtGui.QBrush(_DISABLED_GREY))


class TopBar(QtWidgets.QWidget):
    changed = QtCore.Signal()
    view_changed = QtCore.Signal(str)
    help_clicked = QtCore.Signal()
    load_clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._n_ports = 0
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(self._build_titlebar())
        outer.addWidget(self._build_controls())

    # ---- title bar -------------------------------------------------------
    def _build_titlebar(self):
        from .logo import logo_pixmap
        bar = QtWidgets.QWidget(); bar.setObjectName("titlebar"); bar.setFixedHeight(34)
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(12, 0, 12, 0)
        logo = QtWidgets.QLabel(); logo.setPixmap(logo_pixmap(26))
        logo.setFixedWidth(32); logo.setAlignment(QtCore.Qt.AlignVCenter)
        title = QtWidgets.QLabel("S-Parameter To Lumped Element Netlist Converter")
        title.setObjectName("title")
        lay.addWidget(logo); lay.addWidget(title); lay.addStretch(1)
        vlab = QtWidgets.QLabel("View"); vlab.setObjectName("viewLabel")
        self.view = QtWidgets.QComboBox()
        self.view.addItems(["Design & Schematic", "Plot"]); self.view.setFixedWidth(180)
        self.view.currentIndexChanged.connect(
            lambda _: self.view_changed.emit("design" if self.view.currentIndex() == 0 else "plot"))
        self.help = QtWidgets.QPushButton("?  Help"); self.help.setObjectName("chip")
        self.help.clicked.connect(self.help_clicked.emit)
        lay.addWidget(vlab); lay.addWidget(self.view); lay.addSpacing(8); lay.addWidget(self.help)
        return bar

    def _labeled(self, text, widget):
        box = QtWidgets.QVBoxLayout(); box.setSpacing(2)
        lab = QtWidgets.QLabel(text); lab.setProperty("class", "fieldLabel")
        box.addWidget(lab); box.addWidget(widget)
        return box

    # ---- controls --------------------------------------------------------
    def _build_controls(self):
        bar = QtWidgets.QWidget(); bar.setObjectName("topbar")
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(16, 8, 16, 10); lay.setSpacing(14)

        self.load = QtWidgets.QPushButton("\U0001F4C2  Load .sNp")
        self.load.setObjectName("primary"); self.load.setFixedHeight(30)
        self.load.clicked.connect(self.load_clicked.emit)

        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("Universal (any N-port)", "universal")
        self.mode.addItem("Structure-specific", "structure")
        self.mode.setFixedWidth(220)

        self.structure = QtWidgets.QComboBox()
        self._struct_ports = {}
        for key, name, nports in structure_items():
            self.structure.addItem(name, key); self._struct_ports[key] = nports
        self.structure.setFixedWidth(180)

        self.pdk = QtWidgets.QComboBox()
        self._pdk_supported = {}
        for key, _name, supported in pdk_items():
            self.pdk.addItem(key, key)           # show the PDK key itself
            self._pdk_supported[key] = supported
        self.pdk.setFixedWidth(180)
        self.pdk.setToolTip("Target PDK. VACASK output is currently only "
                            "supported for the IHP PDKs; the others are disabled.")
        self._grey_pdks()

        self.order = QtWidgets.QSpinBox(); self.order.setRange(2, 40); self.order.setValue(6)
        self.order.setFixedWidth(92)

        self.passive = QtWidgets.QCheckBox("Enforce passivity"); self.passive.setChecked(True)

        self.reset = QtWidgets.QPushButton("  Reset")
        self.reset.setIcon(_reset_icon()); self.reset.setIconSize(QtCore.QSize(16, 16))
        self.reset.setFixedHeight(30)
        self.reset.setToolTip("Reset the conversion settings to their defaults.")

        lay.addLayout(self._labeled("", self.load))
        lay.addSpacing(6)
        lay.addLayout(self._labeled("Mode", self.mode))
        lay.addLayout(self._labeled("Structure", self.structure))
        lay.addLayout(self._labeled("PDK", self.pdk))
        lay.addLayout(self._labeled("Max order", self.order))
        lay.addLayout(self._labeled("", self.passive))
        lay.addStretch(1)
        lay.addLayout(self._labeled("", self.reset))

        self.mode.currentIndexChanged.connect(self._on_change)
        self.structure.currentIndexChanged.connect(self._on_change)
        self.pdk.currentIndexChanged.connect(self._on_change)   # may grey a structure
        self.order.valueChanged.connect(lambda _=None: self.changed.emit())
        self.passive.toggled.connect(lambda _=None: self.changed.emit())
        self.reset.clicked.connect(self._on_reset)
        self._apply_constraints()
        return bar

    # ---- reset / view helpers --------------------------------------------
    def _on_reset(self):
        """Restore every control to the ConverterState defaults, then recompute once."""
        widgets = (self.mode, self.structure, self.pdk, self.order, self.passive)
        for w in widgets:
            w.blockSignals(True)
        self.mode.setCurrentIndex(0)                       # universal
        si = self.structure.findData("inductor-pi")
        if si >= 0:
            self.structure.setCurrentIndex(si)
        pi = self.pdk.findData(DEFAULT_PDK)
        if pi >= 0:
            self.pdk.setCurrentIndex(pi)
        self.order.setValue(6)
        self.passive.setChecked(True)
        for w in widgets:
            w.blockSignals(False)
        self._apply_constraints()
        self.changed.emit()

    def set_view(self, name):
        """Select the Design (name='design') or Plot (name='plot') view."""
        self.view.setCurrentIndex(0 if name == "design" else 1)

    # ---- PDK greying (static: unsupported kits can never be chosen) -------
    def _grey_pdks(self):
        first_ok = None
        for i in range(self.pdk.count()):
            key = self.pdk.itemData(i)
            ok = self._pdk_supported.get(key, False)
            _set_item_enabled(self.pdk, i, ok)
            if ok and first_ok is None:
                first_ok = i
        cur = self.pdk.itemData(self.pdk.currentIndex())
        if not self._pdk_supported.get(cur, False) and first_ok is not None:
            self.pdk.setCurrentIndex(first_ok)

    # ---- constraints -----------------------------------------------------
    def set_ports(self, n_ports):
        self._n_ports = n_ports
        self._apply_constraints()

    def _apply_constraints(self):
        is_struct = self.mode.currentData() == "structure"
        self.structure.setEnabled(is_struct)
        self.order.setEnabled(not is_struct)
        self.passive.setEnabled(not is_struct)
        # grey structures that don't match the loaded port count or aren't
        # available for the selected PDK (e.g. no MIM in ihp-sg13cmos5l)
        excluded = excluded_structures(self.pdk.currentData())
        cur = self.structure.currentIndex()
        first_ok = None
        cur_ok = False
        for i in range(self.structure.count()):
            key = self.structure.itemData(i)
            port_ok = (self._n_ports == 0) or (self._struct_ports.get(key) == self._n_ports)
            ok = port_ok and key not in excluded
            _set_item_enabled(self.structure, i, ok)
            if ok and first_ok is None:
                first_ok = i
            if i == cur:
                cur_ok = ok
        if is_struct and not cur_ok and first_ok is not None:
            self.structure.blockSignals(True)
            self.structure.setCurrentIndex(first_ok)
            self.structure.blockSignals(False)

    def _on_change(self, *_):
        self._apply_constraints()
        self.changed.emit()

    def values(self) -> dict:
        return {
            "mode": self.mode.currentData(),
            "structure_key": self.structure.currentData(),
            "pdk": self.pdk.currentData(),
            "max_order": int(self.order.value()),
            "enforce_passivity": bool(self.passive.isChecked()),
        }
