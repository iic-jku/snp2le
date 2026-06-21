"""top_bar.py - control strip.

Dark title bar: snp2le logo + title, then (right) View selector + Help.
Light controls row: Load .sNp, Mode (Universal / Structure), Structure, Max
order, Enforce passivity.  Structures that do not match the loaded port count are
greyed out so an invalid choice can never be made.
"""
from __future__ import annotations
import math
from PySide6 import QtCore, QtGui, QtWidgets

from core.structures import structure_items
from core import xschem
from core.units import parse_eng, format_eng
from .style import JKU_BLUE, JKU_GREEN, JKU_RED
from .widgets import FitComboBox

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


def _load_icon(color="#ffffff"):
    """A simple folder QIcon, drawn (not an emoji) so it renders on every platform
    including the Linux container where the emoji glyph is missing."""
    pm = QtGui.QPixmap(32, 32); pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(QtCore.Qt.NoPen); p.setBrush(QtGui.QColor(color))
    p.drawRoundedRect(QtCore.QRectF(6, 9.5, 9, 5), 1.5, 1.5)       # tab
    p.drawRoundedRect(QtCore.QRectF(6, 12, 20, 12.5), 2.0, 2.0)    # body
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
    export_clicked = QtCore.Signal(str)      # "ngspice" | "vacask"
    load_sch_clicked = QtCore.Signal()       # pick an Xschem testbench
    run_sim_clicked = QtCore.Signal()        # simulate the selected testbench
    reset_clicked = QtCore.Signal()          # restore the freshly-opened state

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
        self.view = FitComboBox("Design & Schematic")
        self.view.addItems(["Design & Schematic", "Plot"])
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
        box.addStretch(1)                      # pin label + widget to the top of the row
        return box

    # ---- controls --------------------------------------------------------
    def _build_controls(self):
        bar = QtWidgets.QWidget(); bar.setObjectName("topbar")
        lay = QtWidgets.QHBoxLayout(bar); lay.setContentsMargins(16, 8, 16, 10); lay.setSpacing(14)

        self.load = QtWidgets.QPushButton("Load .sNp")
        self.load.setObjectName("primary"); self.load.setFixedHeight(30)
        self.load.setIcon(_load_icon()); self.load.setIconSize(QtCore.QSize(16, 16))
        self.load.clicked.connect(self.load_clicked.emit)

        self.mode = FitComboBox("Universal (any N-port)")
        self.mode.addItem("Universal (any N-port)", "universal")
        self.mode.addItem("Structure-specific", "structure")

        self.structure = FitComboBox("MIM capacitor")
        self._struct_ports = {}
        for key, name, nports in structure_items():
            self.structure.addItem(name, key); self._struct_ports[key] = nports

        # extraction frequency (structure modes); accepts eng. notation e.g. '10 GHz'
        self.f_ext = QtWidgets.QLineEdit("10 GHz"); self.f_ext.setFixedWidth(92)
        self.f_ext.setToolTip("Frequency at which the lumped element values are extracted.")
        self._f_extract_hz = 10e9

        # RLGC ladder stage count (transmission-line model only)
        self.stages = QtWidgets.QSpinBox(); self.stages.setRange(1, 20); self.stages.setValue(2)
        self.stages.setFixedWidth(70)
        self.stages.setToolTip("Number of RLGC ladder stages (transmission-line model).")

        self.order = QtWidgets.QSpinBox(); self.order.setRange(2, 40); self.order.setValue(6)
        self.order.setFixedWidth(92)

        self.passive = QtWidgets.QCheckBox("Enforce passivity"); self.passive.setChecked(True)

        # export buttons live here (not in the netlist panel) so they are reachable
        # from the Plot view too
        self.exp_ng = QtWidgets.QPushButton("Export Ngspice")
        self.exp_ng.setObjectName("primary"); self.exp_ng.setFixedHeight(30)
        self.exp_va = QtWidgets.QPushButton("Export VACASK")
        self.exp_va.setFixedHeight(30); self.exp_va.setEnabled(False)

        # Xschem testbench: load a .sch and simulate it; only usable if xschem
        # is installed (checked once), otherwise both are greyed out
        self.load_sch = QtWidgets.QPushButton("Load .sch")
        self.load_sch.setObjectName("primary"); self.load_sch.setFixedHeight(30)
        self.load_sch.setIcon(_load_icon()); self.load_sch.setIconSize(QtCore.QSize(16, 16))
        self.run_sim = QtWidgets.QPushButton("Run Simulation")
        self.run_sim.setFixedHeight(30)
        # when off, the run suppresses ngspice's interactive console + plot windows
        self.sim_output = QtWidgets.QCheckBox("Ngspice output")
        self.sim_output.setChecked(False)
        self.sim_output.setToolTip(
            "Show ngspice's interactive console and plot windows during the run.\n"
            "Uncheck to run quietly (results are still imported into the plot).")
        # 'successful!' / 'failed!' shown below the checkbox after a run
        self.sim_status = QtWidgets.QLabel("")
        self.sim_status.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom)
        if not xschem.available():
            tip = "Xschem was not found on PATH"
            self.sim_output.setEnabled(False); self.sim_output.setToolTip(tip)
            for b in (self.load_sch, self.run_sim):
                b.setEnabled(False); b.setToolTip(tip)

        self.reset = QtWidgets.QPushButton("  Reset")
        self.reset.setIcon(_reset_icon()); self.reset.setIconSize(QtCore.QSize(16, 16))
        self.reset.setFixedHeight(30)
        self.reset.setToolTip("Reset the conversion settings to their defaults.")

        lay.addLayout(self._labeled("", self.load))
        lay.addSpacing(6)
        lay.addLayout(self._labeled("Mode", self.mode))
        lay.addLayout(self._labeled("Structure", self.structure))
        lay.addLayout(self._labeled("<i>f</i><sub>ext</sub>", self.f_ext))
        lay.addLayout(self._labeled("Stages", self.stages))
        lay.addLayout(self._labeled("Max order", self.order))
        lay.addLayout(self._labeled("", self.passive))
        lay.addStretch(1)
        lay.addLayout(self._labeled("", self.exp_ng))
        lay.addLayout(self._labeled("", self.exp_va))
        lay.addLayout(self._labeled("", self.load_sch))
        lay.addLayout(self._labeled("", self.run_sim))
        # 'Ngspice output' sits at the widget row (level with 'Enforce passivity');
        # the status text drops below it, bottom-aligned with the buttons' bottom edge.
        # An inner box one button tall holds both: checkbox at top, status at bottom.
        sim_box = QtWidgets.QVBoxLayout(); sim_box.setSpacing(2)
        sim_band = QtWidgets.QLabel(""); sim_band.setProperty("class", "fieldLabel")
        sim_inner = QtWidgets.QWidget(); sim_inner.setFixedHeight(30)
        il = QtWidgets.QVBoxLayout(sim_inner)
        il.setContentsMargins(0, 0, 0, 0); il.setSpacing(0)
        il.addWidget(self.sim_output, 0, QtCore.Qt.AlignTop)
        il.addStretch(1)
        il.addWidget(self.sim_status, 0, QtCore.Qt.AlignBottom)
        sim_box.addWidget(sim_band)
        sim_box.addWidget(sim_inner)
        sim_box.addStretch(1)
        lay.addLayout(sim_box)
        lay.addLayout(self._labeled("", self.reset))

        self.mode.currentIndexChanged.connect(self._on_change)
        self.structure.currentIndexChanged.connect(self._on_change)
        self.f_ext.editingFinished.connect(self._on_fext)
        self.stages.valueChanged.connect(lambda _=None: self.changed.emit())
        self.order.valueChanged.connect(lambda _=None: self.changed.emit())
        self.passive.toggled.connect(lambda _=None: self.changed.emit())
        self.exp_ng.clicked.connect(lambda: self.export_clicked.emit("ngspice"))
        self.exp_va.clicked.connect(lambda: self.export_clicked.emit("vacask"))
        self.load_sch.clicked.connect(self.load_sch_clicked.emit)
        self.run_sim.clicked.connect(self.run_sim_clicked.emit)
        self.reset.clicked.connect(self.reset_clicked.emit)
        self._apply_constraints()
        return bar

    # ---- reset / view helpers --------------------------------------------
    def reset_controls(self):
        """Restore every control to its default, without triggering a recompute.

        Also unticks 'Ngspice output' and clears the run-status label so the bar
        matches a freshly-opened window; the caller recomputes once."""
        widgets = (self.mode, self.structure, self.stages, self.order,
                   self.passive, self.sim_output)
        for w in widgets:
            w.blockSignals(True)
        self.mode.setCurrentIndex(0)                       # universal
        si = self.structure.findData("inductor-pi")
        if si >= 0:
            self.structure.setCurrentIndex(si)
        self.stages.setValue(2)
        self.order.setValue(6)
        self.passive.setChecked(True)
        self.sim_output.setChecked(False)
        for w in widgets:
            w.blockSignals(False)
        self._set_fext(10e9)                               # default extraction freq
        self.clear_sim_status()
        self._apply_constraints()

    def set_view(self, name):
        """Select the Design (name='design') or Plot (name='plot') view."""
        self.view.setCurrentIndex(0 if name == "design" else 1)

    def set_sim_status(self, text, ok):
        """Show the run outcome: status text and the Run Simulation button in JKU
        green (ok) or red, the button white + bold like the primary buttons."""
        self.sim_status.setText(text)
        self.sim_status.setStyleSheet(
            f"color:{JKU_GREEN if ok else JKU_RED}; font-size:11px; font-weight:700;")
        self.run_sim.setObjectName("runOk" if ok else "runFail")
        self._repolish(self.run_sim)

    def clear_sim_status(self):
        self.sim_status.setText("")
        self.run_sim.setObjectName("")           # back to the default button colour
        self._repolish(self.run_sim)

    @staticmethod
    def _repolish(w):
        """Re-evaluate the stylesheet after an objectName change."""
        w.style().unpolish(w); w.style().polish(w); w.update()

    def set_values(self, state):
        """Apply a ConverterState to the controls (e.g. after loading a design).

        Signals are blocked so this does not trigger a recompute; the caller
        recomputes once afterwards.
        """
        widgets = (self.mode, self.structure, self.stages, self.order, self.passive)
        for w in widgets:
            w.blockSignals(True)
        mi = self.mode.findData(state.mode)
        if mi >= 0:
            self.mode.setCurrentIndex(mi)
        si = self.structure.findData(state.structure_key)
        if si >= 0:
            self.structure.setCurrentIndex(si)
        self.stages.setValue(int(state.n_segments))
        self.order.setValue(int(state.max_order))
        self.passive.setChecked(bool(state.enforce_passivity))
        for w in widgets:
            w.blockSignals(False)
        self._set_fext(float(state.f_extract))
        self._apply_constraints()

    # ---- constraints -----------------------------------------------------
    def set_ports(self, n_ports):
        self._n_ports = n_ports
        self._apply_constraints()

    def _apply_constraints(self):
        is_struct = self.mode.currentData() == "structure"
        self.structure.setEnabled(is_struct)
        self.f_ext.setEnabled(is_struct)           # extraction freq: structure modes only
        self.stages.setEnabled(                    # stages: RLGC line model only
            is_struct and self.structure.currentData() == "tline-rlgc")
        self.order.setEnabled(not is_struct)
        self.passive.setEnabled(not is_struct)
        # grey structures that don't match the loaded port count
        cur = self.structure.currentIndex()
        first_ok = None
        cur_ok = False
        for i in range(self.structure.count()):
            key = self.structure.itemData(i)
            ok = (self._n_ports == 0) or (self._struct_ports.get(key) == self._n_ports)
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

    def _set_fext(self, hz):
        """Set the extraction-frequency field + stored value (no recompute)."""
        self._f_extract_hz = float(hz)
        self.f_ext.setText(format_eng(hz, "Hz"))
        self.f_ext.setProperty("error", False)
        self._repolish(self.f_ext)

    def _on_fext(self):
        """Parse the field on edit; recompute only on a valid, changed value."""
        try:
            v = parse_eng(self.f_ext.text())
            if not v > 0:
                raise ValueError
        except ValueError:
            self.f_ext.setProperty("error", True)      # red field, keep last good value
            self._repolish(self.f_ext)
            return
        self.f_ext.setProperty("error", False)
        self._repolish(self.f_ext)
        if v != self._f_extract_hz:
            self._f_extract_hz = v
            self.changed.emit()

    def values(self) -> dict:
        return {
            "mode": self.mode.currentData(),
            "structure_key": self.structure.currentData(),
            "f_extract": self._f_extract_hz,
            "n_segments": int(self.stages.value()),
            "max_order": int(self.order.value()),
            "enforce_passivity": bool(self.passive.isChecked()),
        }
