# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""top_bar.py - control strip.

Dark title bar: snp2le logo + title, then (right) View selector + Help.
Light controls row: Load .sNp, Mode (Universal / Structure), Structure, Max
order, Enforce passivity, Passivity ceiling, Fit range (GHz).  Structures that do not match
the loaded port count are greyed out so an invalid choice can never be made, and the
passivity ceiling is greyed out (pinned to its strict default) while passivity is not
enforced.
"""
from __future__ import annotations
import math
from PySide6 import QtCore, QtGui, QtWidgets

from snp2le import __version__
from snp2le.core.structures import structure_items
from snp2le.core import xschem
from snp2le.core.units import parse_eng, format_eng
from snp2le.core.universal import (PASSIVITY_CEILING_DEFAULT, PASSIVITY_CEILING_MAX,
                                   PASSIVITY_CEILING_MIN, clamp_passivity_ceiling)
from .style import JKU_BLUE, JKU_GRAY, JKU_GREEN, JKU_RED, PANEL_BORDER, DISABLED_FG
from .widgets import FitComboBox

_DISABLED_GREY = QtGui.QColor(DISABLED_FG)     # greyed-out dropdown items


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
        ver = QtWidgets.QLabel(f"v{__version__}"); ver.setObjectName("version")
        lay.addWidget(logo); lay.addWidget(title); lay.addWidget(ver); lay.addStretch(1)
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

    def _labeled_widget(self, text, widget):
        """Like _labeled but wrapped in a QWidget so the whole group (label + widget)
        can be shown/hidden as a unit (used for the structure-specific options)."""
        w = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(w); box.setContentsMargins(0, 0, 0, 0); box.setSpacing(2)
        lab = QtWidgets.QLabel(text); lab.setProperty("class", "fieldLabel")
        box.addWidget(lab); box.addWidget(widget); box.addStretch(1)
        return w

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

        # extraction frequency (structure modes). Accepts eng. notation e.g. '10 GHz'
        self.f_ext = QtWidgets.QLineEdit("10 GHz"); self.f_ext.setFixedWidth(92)
        self.f_ext.setToolTip("Frequency at which the lumped element values are extracted.")
        self._f_extract_hz = 10e9

        # RLGC ladder stage count (transmission-line model only)
        self.stages = QtWidgets.QSpinBox(); self.stages.setRange(1, 10); self.stages.setValue(2)
        self.stages.setFixedWidth(70)
        self.stages.setToolTip("Number of RLGC ladder stages, 1 to 10 (transmission-line model).")

        # Wilkinson isolation resistor / branch-line resistive loss (model-specific)
        self.iso_r = QtWidgets.QCheckBox("Isolation R"); self.iso_r.setChecked(True)
        self.iso_r.setToolTip("Include the modelled resistance (Wilkinson isolation "
                              "resistor 2*Z0, or branch-line arm loss).\n"
                              "Uncheck to drop it.")
        # reserve room for the longest label so the option slot width never changes
        self.iso_r.setMinimumWidth(
            self.iso_r.fontMetrics().horizontalAdvance("Resistive loss") + 28)

        self.order = QtWidgets.QSpinBox(); self.order.setRange(2, 40); self.order.setValue(6)
        self.order.setFixedWidth(66)          # two digits plus the arrows, no more

        # two lines: the bar is wide enough as it is, and the box reads the same
        self.passive = QtWidgets.QCheckBox("Enforce\npassivity")
        self.passive.setChecked(True)
        self.passive.setToolTip(
            "Perturb the fit until its worst singular value is at or below the\n"
            "Passivity ceiling, so a transient run cannot draw energy out of the model.\n"
            "It costs fit accuracy. Untick to export the raw fit untouched, whatever it\n"
            "measures.")

        # Passivity ceiling: the sigma_max the perturbation works towards.  It only means
        # something while enforcement is running, so the field is greyed and pinned to the
        # default when 'Enforce passivity' is off (see universal.effective_ceiling, which
        # is the single source of that rule).
        self._p_ceiling = PASSIVITY_CEILING_DEFAULT
        self.p_ceiling = QtWidgets.QLineEdit(); self.p_ceiling.setFixedWidth(76)
        self.p_ceiling.setToolTip(
            "Largest singular value the enforced model is allowed to keep.\n"
            f"{PASSIVITY_CEILING_MIN:.2f} is strict passivity: the model can never "
            "deliver more power than it absorbs.\n"
            "A higher ceiling leaves that much gain at the model's worst frequency and "
            "buys back\naccuracy in exchange, since the perturbation has less to "
            "correct.\n"
            "A ceiling above what the fit already measures leaves it untouched.\n"
            f"Range {PASSIVITY_CEILING_MIN:.2f} to {PASSIVITY_CEILING_MAX:.2f}. A value "
            "outside it is replaced by the limit it overshot.\n"
            "Only applies while 'Enforce passivity' is ticked.")
        self._set_ceiling(PASSIVITY_CEILING_DEFAULT)           # show the default, not an empty box

        # structure-specific options live in their own containers so each can be shown
        # only for the structure it belongs to (otherwise hidden entirely)
        self.stages_box = self._labeled_widget("Stages", self.stages)
        self.iso_r_box = self._labeled_widget("", self.iso_r)
        # a stacked slot sized to its widest page holds whichever option applies, so
        # selecting one never changes the bar width (window opens wide and stays put)
        self.opt_box = QtWidgets.QStackedWidget()
        self._opt_empty = QtWidgets.QWidget()
        for w in (self._opt_empty, self.stages_box, self.iso_r_box):
            self.opt_box.addWidget(w)

        # the controls between Structure and the divider depend on the mode: universal
        # shows max order + passivity, structure shows f_ext + the option.  A stack
        # holds both pages and reserves the wider one, so the bar width and the divider
        # position never change with the mode either.
        self.uni_page = QtWidgets.QWidget()
        up = QtWidgets.QHBoxLayout(self.uni_page); up.setContentsMargins(0, 0, 0, 0)
        up.setSpacing(14)
        up.addLayout(self._labeled("Max order", self.order))
        up.addLayout(self._labeled("", self.passive))
        up.addLayout(self._labeled("Passivity ceiling", self.p_ceiling))
        up.addStretch(1)
        self.struct_page = QtWidgets.QWidget()
        sp = QtWidgets.QHBoxLayout(self.struct_page); sp.setContentsMargins(0, 0, 0, 0)
        sp.setSpacing(14)
        sp.addLayout(self._labeled("<i>f</i><sub>ext</sub>", self.f_ext))
        sp.addWidget(self.opt_box); sp.addStretch(1)
        self.mode_stack = QtWidgets.QStackedWidget()
        self.mode_stack.addWidget(self.uni_page); self.mode_stack.addWidget(self.struct_page)

        # fit range: the band of the loaded file the model is fitted to.  It applies to
        # both modes, so it sits outside the mode stack.  Both fields are in GHz (the
        # unit is in the group label, so there is nothing to type but the number) and
        # are filled with the loaded file's own span, so the band on screen is always
        # the band being fitted.  An emptied field means "open on that side".
        self._f_min_hz = None
        self._f_max_hz = None
        self._band_shown = ["", ""]        # text last written, to spot an untouched field
        self.f_min = QtWidgets.QLineEdit(); self.f_min.setFixedWidth(56)
        self.f_max = QtWidgets.QLineEdit(); self.f_max.setFixedWidth(56)
        self.f_min.setPlaceholderText("start"); self.f_max.setPlaceholderText("stop")
        band_tip = ("Frequency band the model is fitted to, in GHz (both modes).\n"
                    "Starts at the loaded file's own range, e.g. 120 to 200.\n"
                    "Narrow it to spend the model order on the band you operate in.")
        for w in (self.f_min, self.f_max):
            w.setToolTip(band_tip)
        band = QtWidgets.QWidget()
        bl = QtWidgets.QHBoxLayout(band)
        bl.setContentsMargins(0, 0, 0, 0); bl.setSpacing(4)
        to_lbl = QtWidgets.QLabel("to"); to_lbl.setProperty("class", "fieldLabel")
        bl.addWidget(self.f_min); bl.addWidget(to_lbl); bl.addWidget(self.f_max)
        self.band_box = self._labeled_widget("Fit range (GHz)", band)
        self.band_box.setToolTip(band_tip)

        # fixed vertical divider between the conversion controls and the action buttons
        self.sep = QtWidgets.QFrame(); self.sep.setFixedWidth(1)
        self.sep.setStyleSheet(f"background-color:{PANEL_BORDER};")
        self.sep.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Expanding)

        # export buttons live here (not in the netlist panel) so they are reachable
        # from the Plot view too
        self.exp_ng = QtWidgets.QPushButton("Export Ngspice")
        self.exp_ng.setObjectName("primary"); self.exp_ng.setFixedHeight(30)
        self.exp_va = QtWidgets.QPushButton("Export VACASK")
        self.exp_va.setObjectName("primary"); self.exp_va.setFixedHeight(30)

        # Xschem testbench: load a .sch and simulate it. Only usable if xschem
        # is installed (checked once), otherwise both are greyed out
        self.load_sch = QtWidgets.QPushButton("Load .sch")
        self.load_sch.setObjectName("primary"); self.load_sch.setFixedHeight(30)
        self.load_sch.setIcon(_load_icon()); self.load_sch.setIconSize(QtCore.QSize(16, 16))
        # simulator used to run the loaded testbench (Ngspice, or VACASK via xschem)
        self.simulator = QtWidgets.QComboBox()
        self.simulator.addItem("Ngspice", "ngspice")
        self.simulator.addItem("VACASK", "vacask")
        self.simulator.setFixedWidth(120)
        self.simulator.setToolTip("Simulator that runs the loaded testbench.\n"
                                  "Auto-set from the testbench name when one is loaded.")
        self.run_sim = QtWidgets.QPushButton("Run Simulation")
        self.run_sim.setFixedHeight(30)
        # when off, the run suppresses the simulator's interactive console + plot windows
        # two lines, like 'Enforce passivity', so the bar stays narrow and the two tick
        # boxes are the same shape (which is what puts them on the same line)
        self.sim_output = QtWidgets.QCheckBox("Show\noutput")
        self.sim_output.setChecked(False)
        self.sim_output.setToolTip(
            "Show the simulator's console and plot windows during the run.\n"
            "Uncheck to run quietly (results are still imported into the plot).")
        # 'successful!' / 'failed!' shown after a run, in the caption slot above the box
        self.sim_status = QtWidgets.QLabel("")
        self.sim_status.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom)
        # a field caption, so its slot is exactly as tall as every other caption in the
        # bar and the tick box below it lines up with 'Enforce passivity' at any DPI.
        # set_sim_status only overrides colour and weight, never the size.
        self.sim_status.setProperty("class", "fieldLabel")
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
        lay.addWidget(self.mode_stack)         # f_ext+option (structure) or order+passivity
        lay.addWidget(self.band_box)           # fit range (both modes)
        lay.addSpacing(12)                     # same gap on both sides of the divider
        lay.addWidget(self.sep)                # fixed divider, always visible
        lay.addSpacing(12)
        lay.addStretch(1)
        lay.addLayout(self._labeled("", self.exp_ng))
        lay.addLayout(self._labeled("", self.exp_va))
        lay.addLayout(self._labeled("", self.load_sch))
        lay.addLayout(self._labeled("Simulator", self.simulator))
        lay.addLayout(self._labeled("", self.run_sim))
        # 'Show output' is built exactly like 'Enforce passivity' (caption slot, then the
        # two-line box), which is what puts the two tick boxes on the same line.  The run
        # status takes the caption slot, empty otherwise: below the box it would have made
        # the whole bar a line taller, and the colour already reads as a status.
        sim_box = QtWidgets.QVBoxLayout(); sim_box.setSpacing(2)
        sim_box.addWidget(self.sim_status)
        sim_box.addWidget(self.sim_output)
        sim_box.addStretch(1)
        lay.addLayout(sim_box)
        lay.addLayout(self._labeled("", self.reset))

        self.mode.currentIndexChanged.connect(self._on_change)
        self.structure.currentIndexChanged.connect(self._on_change)
        self.f_ext.editingFinished.connect(self._on_fext)
        self.f_min.editingFinished.connect(self._on_band)
        self.f_max.editingFinished.connect(self._on_band)
        self.stages.valueChanged.connect(lambda _=None: self.changed.emit())
        self.iso_r.toggled.connect(lambda _=None: self.changed.emit())
        self.order.valueChanged.connect(lambda _=None: self.changed.emit())
        self.passive.toggled.connect(self._on_change)      # also greys the ceiling field
        self.p_ceiling.editingFinished.connect(self._on_ceiling)
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

        Also unticks 'Show output' and clears the run-status label so the bar
        matches a freshly-opened window. The caller recomputes once."""
        widgets = (self.mode, self.structure, self.stages, self.iso_r, self.order,
                   self.passive, self.sim_output, self.simulator)
        for w in widgets:
            w.blockSignals(True)
        self.mode.setCurrentIndex(0)                       # universal
        si = self.structure.findData("inductor-pi")
        if si >= 0:
            self.structure.setCurrentIndex(si)
        self.stages.setValue(2)
        self.iso_r.setChecked(True)
        self.order.setValue(6)
        self.passive.setChecked(True)
        self._set_ceiling(PASSIVITY_CEILING_DEFAULT)
        self.sim_output.setChecked(False)
        self.simulator.setCurrentIndex(0)                  # Ngspice
        for w in widgets:
            w.blockSignals(False)
        self._set_fext(10e9)                               # default extraction freq
        self._set_band(None, None)                         # full range again
        self.clear_sim_status()
        self._apply_constraints()

    def set_simulator(self, key):
        """Select the simulator ('ngspice' / 'vacask'), e.g. from the testbench name."""
        i = self.simulator.findData(key)
        if i >= 0:
            self.simulator.setCurrentIndex(i)

    def set_view(self, name):
        """Select the Design (name='design') or Plot (name='plot') view."""
        self.view.setCurrentIndex(0 if name == "design" else 1)

    def set_sim_status(self, text, ok):
        """Show the run outcome: status text and the Run Simulation button in JKU
        green (ok) or red, the button white + bold like the primary buttons."""
        self.sim_status.setText(text)
        self.sim_status.setStyleSheet(
            f"color:{JKU_GREEN if ok else JKU_RED}; font-weight:700;")
        self.run_sim.setObjectName("runOk" if ok else "runFail")
        self._repolish(self.run_sim)

    def set_sim_progress(self, text):
        """Show a neutral in-progress status (e.g. 'running...') in grey, leaving the
        button at its default colour. It doubles as the Stop button while a run is on."""
        self.sim_status.setText(text)
        self.sim_status.setStyleSheet(f"color:{JKU_GRAY}; font-weight:600;")
        self.run_sim.setObjectName("")
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

        Signals are blocked so this does not trigger a recompute. The caller
        recomputes once afterwards.
        """
        widgets = (self.mode, self.structure, self.stages, self.iso_r, self.order,
                   self.passive)
        for w in widgets:
            w.blockSignals(True)
        mi = self.mode.findData(state.mode)
        if mi >= 0:
            self.mode.setCurrentIndex(mi)
        si = self.structure.findData(state.structure_key)
        if si >= 0:
            self.structure.setCurrentIndex(si)
        self.stages.setValue(int(state.n_segments))
        self.iso_r.setChecked(bool(state.iso_resistor))
        self.order.setValue(int(state.max_order))
        self.passive.setChecked(bool(state.enforce_passivity))
        for w in widgets:
            w.blockSignals(False)
        self._set_ceiling(state.passivity_ceiling)
        self._set_fext(float(state.f_extract))
        self._set_band(state.f_min, state.f_max)
        self._apply_constraints()

    # ---- constraints -----------------------------------------------------
    def set_ports(self, n_ports):
        self._n_ports = n_ports
        self._apply_constraints()

    def _apply_constraints(self):
        is_struct = self.mode.currentData() == "structure"
        # nothing aims at the ceiling without enforcement, so the field greys out and
        # returns to its default, keeping what is shown equal to what the fit uses
        if self.passive.isChecked():
            self.p_ceiling.setEnabled(True)
        else:
            self.p_ceiling.setEnabled(False)
            if self._p_ceiling != PASSIVITY_CEILING_DEFAULT:
                self._set_ceiling(PASSIVITY_CEILING_DEFAULT)
        self.structure.setEnabled(is_struct)       # greyed in universal mode
        # show the mode's own controls: structure -> f_ext + option, universal -> order + passivity
        self.mode_stack.setCurrentWidget(self.struct_page if is_struct else self.uni_page)
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
        # structure-specific option: show only the page for the chosen structure
        key = self.structure.currentData()
        self.iso_r.setText("Resistive loss" if key == "branchline" else "Isolation R")
        if is_struct and key == "tline-rlgc":               # RLGC line only
            self.opt_box.setCurrentWidget(self.stages_box)
        elif is_struct and key in ("wilkinson-inphase", "branchline"):
            self.opt_box.setCurrentWidget(self.iso_r_box)   # isolation R / resistive loss
        else:
            self.opt_box.setCurrentWidget(self._opt_empty)

    def _on_change(self, *_):
        self._apply_constraints()
        self.changed.emit()

    def _set_fext(self, hz):
        """Set the extraction-frequency field + stored value (no recompute)."""
        self._f_extract_hz = float(hz)
        self.f_ext.setText(format_eng(hz, "Hz"))
        self.f_ext.setProperty("error", False)
        self._repolish(self.f_ext)

    def show_fext(self, hz):
        """Mirror the actually-used extraction frequency into the field (e.g. the
        auto-detected centre frequency), without triggering a recompute."""
        if hz and abs(float(hz) - self._f_extract_hz) > 1e-3:
            self._set_fext(hz)

    def _set_ceiling(self, value):
        """Set the passivity-ceiling field + stored value (no recompute).

        The value is clamped first, so the field can never show a ceiling outside the
        allowed range, not even from a hand-edited design file."""
        self._p_ceiling = clamp_passivity_ceiling(value)
        self.p_ceiling.setText(f"{self._p_ceiling:.2f}")

    def _on_ceiling(self):
        """Parse the field on edit and recompute when the value actually changed.

        An out-of-range number is replaced by the limit it overshot, so typing 9.9 leaves
        1.20 in the field and typing 0.5 leaves 1.00.  Showing the limit is how someone
        who has not read the tooltip discovers it, and it beats f_ext's red field here
        because this input has only two edges to hit.  Text that is not a number at all
        has no edge to clamp to and falls back to the strict ceiling.  A decimal comma is
        accepted."""
        try:
            v = float(self.p_ceiling.text().strip().replace(",", "."))
        except ValueError:
            v = None
        v = clamp_passivity_ceiling(v)            # out of range -> the nearest limit
        changed = v != self._p_ceiling
        self._set_ceiling(v)                       # also normalises the text, '1,1' -> '1.10'
        if changed:
            self.changed.emit()

    def _on_fext(self):
        """Parse the field on edit, recompute only on a valid, changed value."""
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

    @staticmethod
    def _ghz_text(hz) -> str:
        """A frequency as the plain GHz number the field shows, e.g. 1.2e11 -> '120'."""
        return f"{float(hz) / 1e9:.6g}"

    @staticmethod
    def _parse_ghz(text):
        """A field entry in GHz as Hz, or None if it is not a positive number.

        The unit lives in the group label, so a bare number is the expected input.  A
        trailing unit somebody typed out of habit is accepted rather than rejected, and
        a decimal comma is read like a decimal point (as the ceiling field does)."""
        t = str(text).strip().replace(",", ".")
        for suffix in ("GHz", "Ghz", "ghz", "G", "g"):
            if t.endswith(suffix):
                t = t[: -len(suffix)].strip()
                break
        try:
            hz = float(t) * 1e9
        except ValueError:
            return None
        return hz if hz > 0 else None

    def _set_band(self, f_min, f_max):
        """Set the fit-range fields + stored values (no recompute).  None clears a
        field, which means "open on that side" (the loaded file's own edge).

        The stored value keeps the full precision it came in with while the field shows
        a rounded GHz number, so redisplaying a file's own edge can never crop the first
        or last sample off the fit."""
        for i, (hz, field, attr) in enumerate(((f_min, self.f_min, "_f_min_hz"),
                                               (f_max, self.f_max, "_f_max_hz"))):
            try:
                hz = None if hz in (None, 0) else float(hz)
            except (TypeError, ValueError):     # a hand-edited design: leave that side open
                hz = None
            setattr(self, attr, hz)
            self._band_shown[i] = "" if hz is None else self._ghz_text(hz)
            field.setText(self._band_shown[i])
            field.setProperty("error", False)
            self._repolish(field)

    def show_band(self, f_min, f_max):
        """Mirror the loaded file's own span into the fit-range fields (no recompute),
        so they are never empty and always name the band that will be fitted."""
        self._set_band(f_min, f_max)

    def _on_band(self):
        """Parse both fit-range fields on edit, recompute only on a valid, changed band.

        Entries are in GHz.  An emptied field is a valid input (that side follows the
        data).  Text that is not a number turns the field red and the last good value is
        kept, exactly like f_ext.  A field still holding exactly what was written into it
        keeps its stored value untouched, so the rounding in the display never becomes
        the band.  Whether the band itself makes sense against the loaded file is decided
        by the converter, which reports it in the Conversion panel."""
        band = []
        for i, (field, attr) in enumerate(((self.f_min, "_f_min_hz"),
                                           (self.f_max, "_f_max_hz"))):
            text = field.text().strip()
            if text == self._band_shown[i]:          # untouched, keep the exact value
                band.append(getattr(self, attr))
                ok = True
            elif not text:
                band.append(None)
                ok = True
            else:
                v = self._parse_ghz(text)
                ok = v is not None
                band.append(v if ok else getattr(self, attr))
            field.setProperty("error", not ok)
            self._repolish(field)
        changed = tuple(band) != (self._f_min_hz, self._f_max_hz)
        self._f_min_hz, self._f_max_hz = band
        # Normalise the display whatever happened, not only on a change: re-entering the
        # same frequency as '150 GHz' would otherwise leave the unit standing in the field.
        for i, (hz, field) in enumerate(((band[0], self.f_min), (band[1], self.f_max))):
            if field.property("error"):
                continue                                     # leave rejected text to fix
            self._band_shown[i] = "" if hz is None else self._ghz_text(hz)
            if field.text().strip() != self._band_shown[i]:
                field.setText(self._band_shown[i])           # '150 GHz' -> '150'
        if changed:
            self.changed.emit()

    def values(self) -> dict:
        return {
            "mode": self.mode.currentData(),
            "structure_key": self.structure.currentData(),
            "f_extract": self._f_extract_hz,
            "n_segments": int(self.stages.value()),
            "iso_resistor": bool(self.iso_r.isChecked()),
            "max_order": int(self.order.value()),
            "enforce_passivity": bool(self.passive.isChecked()),
            "passivity_ceiling": float(self._p_ceiling),
            "f_min": self._f_min_hz,
            "f_max": self._f_max_hz,
        }
