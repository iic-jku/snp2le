"""plot_view.py - the "Plot" page.

Four S-parameters are shown side by side.  Each column shows magnitude (dB, top)
and phase (deg, bottom) of one selected S_ij; the four selectors default to the
2-port set S11/S21/S12/S22.  Each panel overlays the loaded data (solid grey),
the fitted/extracted model (blue long dashes) and, once imported, an ngspice
simulation table (red dash-dot, drawn thicker on top) on its own frequency grid.

Each panel has a live mouse read-out and a "marker mode": with it on, clicking a
curve drops a labelled data-point marker (up to three per panel), clicking a
marker removes it, and right-clicking clears them all.  Plots pop out, export to
CSV, and can import an ngspice simulation to overlay.
"""
from __future__ import annotations
import csv
import os
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from matplotlib.backend_bases import _Mode

from .style import JKU_BLUE, JKU_GRAY, JKU_RED
from .widgets import passivity_text, FitComboBox
from core import io

# Curve styling: JKU colours paired with distinct line styles, so the traces
# stay readable in black-and-white and for colour-blind viewers.  `data` is the
# loaded Touchstone, `model` the fit/extraction, `sim` an imported ngspice
# simulation.  Each entry is (label, colour, matplotlib line style); the dash
# tuples are (offset, (on, off)) in points.
CURVE_STYLES = [
    ("data",       JKU_GRAY,  "-"),                  # solid
    ("model",      JKU_BLUE,  (0, (7, 3))),          # long dashes
    ("simulation", JKU_RED,   (0, (5, 2, 1, 2))),    # dash-dot, high contrast vs model
]
DATA, MODEL, SIM = CURVE_STYLES[0], CURVE_STYLES[1], CURVE_STYLES[2]
SIDES = ["A", "B", "C", "D"]
DEFAULTS = ["S11", "S21", "S12", "S22"]

# matplotlib named line style -> Qt pen style, for drawing matching legend
# swatches; dash-tuple styles are converted on the fly in _qt_pen.
_QT_DASH = {
    "-": QtCore.Qt.SolidLine, "--": QtCore.Qt.DashLine,
    "-.": QtCore.Qt.DashDotLine, ":": QtCore.Qt.DotLine,
}


def _qt_pen(color, linestyle, width=2.0):
    """A QPen matching a matplotlib line style (named string or (offset, (on,
    off)) dash tuple), so legend swatches mirror the plotted curves."""
    pen = QtGui.QPen(QtGui.QColor(color), width)
    # flat cap: the default square cap extends each dash by half the line width,
    # which fills the gaps of short dashes and makes them look solid
    pen.setCapStyle(QtCore.Qt.FlatCap)
    if isinstance(linestyle, (tuple, list)):
        _, seq = linestyle
        pen.setStyle(QtCore.Qt.CustomDashLine)
        # Qt dash units are multiples of the pen width; matplotlib's are points
        pen.setDashPattern([max(0.5, v / width) for v in seq])
    else:
        pen.setStyle(_QT_DASH.get(linestyle, QtCore.Qt.SolidLine))
    return pen

_TB_QSS = """
QToolBar { background:transparent; border:none; spacing:1px; }
QToolButton { background:transparent; border:none; padding:2px; border-radius:4px;
    color:#000000; font-size:13px; font-weight:700; min-width:16px; }
QToolButton:hover { background:#e7ecf3; }
QToolButton:checked { background:#d3e6f1; }
"""


class _MiniToolbar(NavigationToolbar2QT):
    """Matplotlib's home/pan/zoom/save toolbar, trimmed and tinted JKU blue.

    Matplotlib recolors its toolbar icons to white when it detects a dark widget
    palette (our app uses a dark stylesheet), which makes them invisible on the
    light plot panels.  We override icon creation to render the shipped SVGs in
    JKU blue instead, for visibility and colour consistency.  Any failure falls
    back to matplotlib's own icon so the toolbar still works.
    """
    toolitems = [t for t in NavigationToolbar2QT.toolitems
                 if t[0] in ("Home", "Pan", "Zoom", "Save")]

    def _icon(self, name):
        try:
            from matplotlib import cbook
            from PySide6.QtSvg import QSvgRenderer
            svg = cbook._get_data_path("images", name).with_suffix(".svg")
            data = (svg.read_bytes()
                    .replace(b"fill:black;", b"fill:" + JKU_BLUE.encode() + b";")
                    .replace(b"stroke:black;", b"stroke:" + JKU_BLUE.encode() + b";"))
            renderer = QSvgRenderer(QtCore.QByteArray(data))
            if not renderer.isValid():
                return super()._icon(name)
            pm = QtGui.QPixmap(32, 32)
            pm.fill(QtCore.Qt.transparent)
            p = QtGui.QPainter(pm)
            renderer.render(p)
            p.end()
            return QtGui.QIcon(pm)
        except Exception:                                 # noqa: BLE001
            return super()._icon(name)


def _marker_icon():
    """A crosshair/target QIcon (JKU blue) for the marker-mode toolbar button."""
    pm = QtGui.QPixmap(32, 32); pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm); p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    col = QtGui.QColor(JKU_BLUE)
    p.setPen(QtGui.QPen(col, 2.2))
    p.drawEllipse(9, 9, 14, 14)                  # ring
    p.setBrush(col)
    p.drawEllipse(14, 14, 4, 4)                  # centre dot
    for a, b, c, d in ((16, 2, 16, 7), (16, 25, 16, 30),
                       (2, 16, 7, 16), (25, 16, 30, 16)):
        p.drawLine(a, b, c, d)                   # crosshair ticks
    p.end()
    return QtGui.QIcon(pm)


def _legend_swatch(color, linestyle):
    """A small QLabel drawing a line in `color` with `linestyle`, so the legend
    shows the same dash pattern as the plotted curve."""
    pm = QtGui.QPixmap(30, 12)
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setPen(_qt_pen(color, linestyle))
    p.drawLine(1, 6, 29, 6)
    p.end()
    lab = QtWidgets.QLabel()
    lab.setPixmap(pm)
    return lab


class _PlotPanel:
    """One plot cell: figure + toolbar + live read-out + click-to-drop markers."""
    MAX_MARKERS = 3
    HIT_PX = 9                       # click-within radius (px) to grab a marker

    def __init__(self, header_title):
        self.frame = QtWidgets.QFrame(); self.frame.setProperty("class", "panel")
        lay = QtWidgets.QVBoxLayout(self.frame)
        lay.setContentsMargins(8, 5, 8, 6); lay.setSpacing(1)

        self.fig = Figure(figsize=(2.7, 2.4)); self.fig.patch.set_facecolor("white")
        self.canvas = FigureCanvas(self.fig)
        self.ax = self.fig.add_subplot(111)

        self.tb = _MiniToolbar(self.canvas, self.frame, coordinates=False)
        self.tb.setIconSize(QtCore.QSize(15, 15)); self.tb.setStyleSheet(_TB_QSS)
        self.tb.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                              QtWidgets.QSizePolicy.Policy.Preferred)
        self._add_marker_tool()

        self.head = QtWidgets.QLabel(header_title)
        self.head.setProperty("class", "panelTitle")
        self.coords = QtWidgets.QLabel(""); self.coords.setProperty("class", "hint")
        self.coords.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        # the read-out may shrink to nothing so the toolbar always fits in one row
        self.coords.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                                  QtWidgets.QSizePolicy.Policy.Preferred)

        header = QtWidgets.QHBoxLayout()
        header.addWidget(self.head); header.addStretch(1)
        header.addWidget(self.coords); header.addSpacing(6); header.addWidget(self.tb)
        lay.addLayout(header); lay.addWidget(self.canvas, 1)

        self.series = []             # [{label, color, x, y}]
        self.markers = []            # [{x, y, point, annot}]
        self.marker_mode = False

        self.canvas.mpl_connect("motion_notify_event", self._on_move)
        self.canvas.mpl_connect("axes_leave_event", lambda _ev: self.coords.setText(""))
        self.canvas.mpl_connect("button_press_event", self._on_click)

    # ---- marker-mode toolbar button --------------------------------------
    def _add_marker_tool(self):
        self.tb.addSeparator()
        self.marker_action = self.tb.addAction(_marker_icon(), "Marker")
        self.marker_action.setCheckable(True)
        self.marker_action.setToolTip(
            "Marker mode: click a curve to drop a marker (up to 3). "
            "Click a marker to remove it, right-click to clear all.")
        self.marker_action.toggled.connect(self._on_marker_toggled)
        # pressing pan or zoom leaves marker mode (mutually exclusive tools)
        for key in ("pan", "zoom"):
            act = self.tb._actions.get(key)
            if act is not None:
                act.toggled.connect(self._tool_toggled)

    def _tool_toggled(self, checked):
        if checked and self.marker_action.isChecked():
            self.marker_action.setChecked(False)

    def _on_marker_toggled(self, checked):
        self.marker_mode = bool(checked)
        if checked:                                   # turn off any active pan/zoom
            if self.tb.mode == _Mode.PAN:
                self.tb.pan()
            elif self.tb.mode == _Mode.ZOOM:
                self.tb.zoom()

    # ---- live coordinate read-out ----------------------------------------
    def _on_move(self, ev):
        if ev.inaxes is self.ax and ev.xdata is not None and ev.ydata is not None:
            self.coords.setText(f"x = {ev.xdata:.3g}   y = {ev.ydata:.4g}")
        else:
            self.coords.setText("")

    # ---- plotting --------------------------------------------------------
    def plot_series(self, x, series, xlabel, ylabel):
        self.ax.clear()
        self.markers = []                    # artists were wiped by clear()
        self.series = []
        x = np.asarray(x, float)
        for s in series:
            y = np.asarray(s["y"], float)
            self.ax.plot(x, y, color=s["color"], ls=s["ls"], lw=s["lw"], label=s["label"])
            self.series.append({"label": s["label"], "color": s["color"], "x": x, "y": y})
        self.ax.set_xlabel(xlabel, fontsize=8)
        self.ax.set_ylabel(ylabel, fontsize=9)
        self.ax.grid(True, alpha=0.3)

    def add_series(self, x, s):
        """Overlay one extra curve (with its own x grid) without clearing."""
        x = np.asarray(x, float); y = np.asarray(s["y"], float)
        self.ax.plot(x, y, color=s["color"], ls=s["ls"], lw=s["lw"], label=s["label"])
        self.series.append({"label": s["label"], "color": s["color"], "x": x, "y": y})

    def mark_fext(self, x, y):
        """Mark the extraction frequency on the model curve (structure modes): the
        point the lumped value was read off, and the centre of the band-drift window."""
        if x is None or y != y:                  # None / NaN
            return
        self.ax.plot([x], [y], marker="o", ms=7.0, mfc=MODEL[1], mec="white",
                     mew=1.1, ls="none", zorder=6)

    def clear_axes(self):
        self.ax.clear(); self.series = []; self.markers = []

    def draw(self):
        self.fig.tight_layout(pad=0.4); self.canvas.draw_idle()

    # ---- markers ---------------------------------------------------------
    def _on_click(self, ev):
        if ev.inaxes is not self.ax:
            return
        if ev.button == 3:                            # right-click clears all
            self._clear_markers(); return
        if ev.button != 1:
            return
        hit = self._marker_at(ev)
        if hit is not None:                           # click a marker to remove it
            self._remove_marker(hit); return
        if not self.marker_mode or self.tb.mode != _Mode.NONE:
            return                                    # placing needs marker mode, no pan/zoom
        if len(self.markers) >= self.MAX_MARKERS or not self.series:
            return
        self._place_marker(ev)

    def _marker_at(self, ev):
        for mk in self.markers:
            px, py = self.ax.transData.transform((mk["x"], mk["y"]))
            if abs(px - ev.x) <= self.HIT_PX and abs(py - ev.y) <= self.HIT_PX:
                return mk
        return None

    def _place_marker(self, ev):
        # snap to the nearest sample of the nearest curve, in pixel space
        best = None
        for s in self.series:
            pts = self.ax.transData.transform(np.column_stack([s["x"], s["y"]]))
            d2 = (pts[:, 0] - ev.x) ** 2 + (pts[:, 1] - ev.y) ** 2
            k = int(np.argmin(d2))
            if best is None or d2[k] < best[0]:
                best = (d2[k], s, k)
        _, s, k = best
        x = float(s["x"][k]); y = float(s["y"][k]); color = s["color"]
        point, = self.ax.plot([x], [y], marker="o", ms=6, mfc=color,
                              mec="white", mew=1.0, ls="none", zorder=6)
        annot = self.ax.annotate(
            f"{s['label']}\nx = {x:.4g}\ny = {y:.4g}",
            xy=(x, y), xytext=(9, 9), textcoords="offset points",
            fontsize=7, ha="left", va="bottom", zorder=7, color="#1a1d21",
            bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=color, lw=1.3, alpha=0.96))
        self.markers.append({"x": x, "y": y, "point": point, "annot": annot})
        self.canvas.draw_idle()

    def _remove_marker(self, mk):
        mk["point"].remove(); mk["annot"].remove()
        self.markers.remove(mk); self.canvas.draw_idle()

    def _clear_markers(self):
        for mk in self.markers:
            mk["point"].remove(); mk["annot"].remove()
        self.markers = []; self.canvas.draw_idle()


class PlotView(QtWidgets.QWidget):
    popped_out = QtCore.Signal()      # plots moved to their own window
    docked = QtCore.Signal()          # plots returned to the main window

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # The controls row and the plot grid live together in one container, so
        # popping out moves the whole panel (selectors + legend + buttons), not
        # just the plots.  objectName "root" gives it the greyish app background
        # so the margins around the plots read as background, not white.
        self._content = QtWidgets.QWidget(); self._content.setObjectName("root")
        content = QtWidgets.QVBoxLayout(self._content)
        content.setContentsMargins(16, 12, 16, 16); content.setSpacing(8)

        bar = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Results"); title.setProperty("class", "panelTitle")
        bar.addWidget(title); bar.addSpacing(12)
        self.selectors = []
        for d in DEFAULTS:
            # sizes to the longest trace label ("Rseries / Rshunt") via Qt's own
            # metrics, so it fits on any platform font; the legend after the
            # selectors shifts left to match
            cb = FitComboBox("Rseries / Rshunt")
            cb.currentIndexChanged.connect(self._render)
            self.selectors.append(cb); bar.addWidget(cb)
        bar.addSpacing(14)
        for name, color, ls in (DATA, MODEL, SIM):
            bar.addWidget(_legend_swatch(color, ls))
            bar.addWidget(self._hint(name)); bar.addSpacing(8)
        bar.addStretch(1)
        # universal-mode status mirrored from the Design tab (passivity + order),
        # placed just before Export CSV; hidden in structure mode
        self.stats_box = QtWidgets.QWidget()
        sb = QtWidgets.QHBoxLayout(self.stats_box)
        sb.setContentsMargins(0, 0, 14, 0); sb.setSpacing(16)
        self.pass_stat = self._stat(); self.order_stat = self._stat()
        sb.addWidget(self.pass_stat); sb.addWidget(self.order_stat)
        bar.addWidget(self.stats_box)
        self.export_btn = QtWidgets.QPushButton("Export CSV")
        self.import_btn = QtWidgets.QPushButton("Import simulation")
        self.popout_btn = QtWidgets.QPushButton("Pop out plots"); self.popout_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.export_csv)
        self.import_btn.clicked.connect(self.import_sim)
        self.popout_btn.clicked.connect(self.toggle_popout)
        bar.addWidget(self.export_btn); bar.addWidget(self.import_btn)
        bar.addWidget(self.popout_btn)
        content.addLayout(bar)

        self.grid_host = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self.grid_host)
        grid.setContentsMargins(0, 0, 0, 0); grid.setSpacing(10)
        self._panels = {}
        for col, side in enumerate(SIDES):
            for row, (kind, t) in enumerate((("mag", "Magnitude  (dB)"),
                                             ("ph", "Phase  (°)"))):
                panel = _PlotPanel(t)
                self._panels[kind + side] = panel
                grid.addWidget(panel.frame, row, col)
        for c in range(len(SIDES)):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch(0, 1); grid.setRowStretch(1, 1)
        content.addWidget(self.grid_host, 1)

        root.addWidget(self._content)

        self._popout = None
        self._res = None
        self._last = None
        self._prev_aux = ()           # aux-trace labels available last update
        self._prev_defaults = ()      # preferred default plot set last update
        self._sim = None              # imported ngspice simulation overlay
        self._last_sim_dir = ""       # remembered import folder

    def _hint(self, text):
        lab = QtWidgets.QLabel(text); lab.setProperty("class", "hint")
        return lab

    def _stat(self):
        """A grey-caption / dark-value status label for the control bar."""
        lab = QtWidgets.QLabel(""); lab.setProperty("class", "hint")
        lab.setTextFormat(QtCore.Qt.RichText)
        return lab

    @staticmethod
    def _stat_html(caption, value):
        return (f"{caption}:&nbsp;&nbsp;"
                f'<b style="color:{JKU_BLUE}">{value}</b>')

    # ---- entry point -----------------------------------------------------
    def update_results(self, res):
        self._res = res
        # mirror the Design tab's passivity + order for the universal macromodel
        if res.mode == "universal":
            self.pass_stat.setText(self._stat_html("passivity", passivity_text(res)))
            self.order_stat.setText(self._stat_html("order", f"{res.n_poles} poles"))
            self.stats_box.setVisible(True)
        else:
            self.stats_box.setVisible(False)
        n = res.n_ports or 0
        aux = list((res.aux_traces or {}).keys())          # e.g. ["Ldiff / Q", ...]
        # extra traces first in the dropdown, then the S-parameters
        items = [(lbl, lbl) for lbl in aux]
        items += [(f"S{i+1}{j+1}", (i, j)) for i in range(n) for j in range(n)]
        # structures may declare preferred defaults; else extra traces then S21,
        # else the plain S-parameter set
        dp = getattr(res, "default_plots", None)
        if dp:
            defaults = (list(dp) + list(DEFAULTS))[:4]
        elif aux:
            defaults = (aux + ["S21", "S11", "S22", "S12"])[:4]
        else:
            defaults = list(DEFAULTS)
        # re-apply defaults when the available extra traces OR the preferred default
        # set change (mode/structure switch); otherwise preserve the user's selections
        reset = (tuple(aux) != self._prev_aux) or (tuple(defaults) != self._prev_defaults)
        self._prev_aux = tuple(aux)
        self._prev_defaults = tuple(defaults)
        for combo, default in zip(self.selectors, defaults):
            cur = combo.currentText()
            combo.blockSignals(True); combo.clear()
            for text, data in items:
                combo.addItem(text, data)
            idx = combo.findText(cur) if (cur and not reset) else -1
            if idx < 0:
                idx = combo.findText(default)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        self._render()

    def _render(self, *_):
        res = self._res
        for panel in self._panels.values():
            panel.clear_axes()
        if res is None or res.data_s is None or res.model_s is None:
            for panel in self._panels.values():
                panel.draw()
            return
        f = np.asarray(res.freq, dtype=float); fg = f / 1e9
        xlabel = r"$f\ \mathrm{(GHz)}$"
        self._last = {"f_Hz": f}
        # extraction-frequency marker: structure modes only (universal has no f_ext)
        fext = res.metrics.get("f_extract") if (res.mode == "structure" and res.metrics) else None
        kx = int(np.argmin(np.abs(f - float(fext)))) if fext else None
        for side, combo in zip(SIDES, self.selectors):
            sel = combo.currentData()
            magp = self._panels["mag" + side]; php = self._panels["ph" + side]
            if isinstance(sel, tuple):                  # an S-parameter
                i, j = sel
                sij = combo.currentText(); sub = sij[1:]
                d = np.asarray(res.data_s)[:, i, j]
                m = np.asarray(res.model_s)[:, i, j]
                mag_d = 20 * np.log10(np.maximum(np.abs(d), 1e-12))
                mag_m = 20 * np.log10(np.maximum(np.abs(m), 1e-12))
                ph_d = np.unwrap(np.angle(d)) * 180 / np.pi
                ph_m = np.unwrap(np.angle(m)) * 180 / np.pi
                magp.head.setText("Magnitude  (dB)")
                magp.plot_series(fg, self._pair(mag_d, mag_m), xlabel,
                                 rf"$|S_{{{sub}}}|\ \mathrm{{(dB)}}$")
                php.head.setText("Phase  (°)")
                php.plot_series(fg, self._pair(ph_d, ph_m), xlabel,
                               rf"$\angle S_{{{sub}}}\ (^\circ)$")
                self._last[f"{sij}|data_dB"] = mag_d
                self._last[f"{sij}|model_dB"] = mag_m
                self._last[f"{sij}|data_deg"] = ph_d
                self._last[f"{sij}|model_deg"] = ph_m
                self._overlay_sim(magp, php, sij)
            elif isinstance(sel, str) and res.aux_traces and sel in res.aux_traces:
                spec = res.aux_traces[sel]
                self._plot_aux(magp, fg, xlabel, spec["top"], f"{sel}|top")
                self._plot_aux(php, fg, xlabel, spec["bottom"], f"{sel}|bottom")

        if kx is not None:                       # mark f_ext on each model curve
            for panel in self._panels.values():
                for s in panel.series:
                    if s["label"] == MODEL[0] and kx < len(s["y"]):
                        panel.mark_fext(float(s["x"][kx]), float(s["y"][kx]))
                        break

        for panel in self._panels.values():
            panel.draw()

    @staticmethod
    def _pair(data_y, model_y):
        return [{"label": DATA[0], "color": DATA[1], "ls": DATA[2], "lw": 1.4, "y": data_y},
                {"label": MODEL[0], "color": MODEL[1], "ls": MODEL[2], "lw": 1.6, "y": model_y}]

    def _plot_aux(self, panel, fg, xlabel, spec, key):
        """Plot one extra-trace subplot (e.g. L_series or Q over frequency)."""
        data_y = np.asarray(spec["data"], float)
        series = [{"label": DATA[0], "color": DATA[1], "ls": DATA[2], "lw": 1.4,
                   "y": data_y}]
        model_y = None
        if spec.get("model") is not None:
            model_y = np.asarray(spec["model"], float)
            series.append({"label": MODEL[0], "color": MODEL[1], "ls": MODEL[2],
                           "lw": 1.6, "y": model_y})
        panel.plot_series(fg, series, xlabel, spec["ylabel"])
        panel.head.setText(spec.get("title", ""))
        # frame the y-axis on the model curve so it fills the axis; resonance poles
        # in the element values and spikes in the measured data simply clip
        ylim = self._frame_ylim(model_y, data_y) or spec.get("ylim")
        if ylim:
            panel.ax.set_ylim(*ylim)
        self._last[f"{key}|data"] = data_y
        if model_y is not None:
            self._last[f"{key}|model"] = model_y

    @staticmethod
    def _frame_ylim(model_y, data_y):
        """Y-limits that frame the model curve over the full axis.

        The element-value curves (L, C, R, Q) can diverge near resonances and the
        measured data can carry large spikes.  A robust body is taken from the 5-95
        percentile band; the axis extends to the true extremum only when it is within
        a few body-widths (so a bounded feature such as the Q peak is kept whole),
        otherwise a runaway pole / spike is clipped.  Falls back to the data when no
        model curve is present."""
        def frame(y):
            if y is None:
                return None
            y = np.asarray(y, float)
            y = y[np.isfinite(y)]
            if y.size == 0:
                return None
            lo_b, hi_b = (float(v) for v in np.percentile(y, [5.0, 95.0]))
            body = hi_b - lo_b
            ymin, ymax = float(np.min(y)), float(np.max(y))
            hi = ymax if ymax <= hi_b + 4.0 * body else hi_b   # keep peak, clip pole
            lo = ymin if ymin >= lo_b - 4.0 * body else lo_b
            return lo, hi

        r = frame(model_y)
        # a (near-)constant model carries no vertical information to frame on - its
        # tiny numerical span would collapse the axis to an unreadable offset range -
        # so frame on the data instead (e.g. a flat transformer L vs its rising data)
        if r is not None and (r[1] - r[0]) <= 1e-3 * max(abs(r[0]), abs(r[1]), 1.0):
            r = frame(data_y) or r
        if r is None:
            return None
        lo, hi = r
        span = hi - lo
        pad = 0.08 * span if span > 1e-3 * max(abs(lo), abs(hi), 1.0) \
            else 0.1 * max(abs(hi), 1.0)
        return lo - pad, hi + pad

    def _overlay_sim(self, magp, php, sij):
        """Overlay the imported simulation for S_ij, if present, on its own grid."""
        if not self._sim or sij not in self._sim:
            return
        sf = np.asarray(self._sim["f"], float) / 1e9
        rec = self._sim[sij]
        if rec.get("db") is not None:
            magp.add_series(sf, {"label": SIM[0], "color": SIM[1], "ls": SIM[2],
                                 "lw": 1.9, "y": rec["db"]})
        if rec.get("deg") is not None:               # unwrap to match data/model
            ph = np.unwrap(np.deg2rad(np.asarray(rec["deg"], float))) * 180 / np.pi
            php.add_series(sf, {"label": SIM[0], "color": SIM[1], "ls": SIM[2],
                                "lw": 1.9, "y": ph})

    # ---- import simulation / CSV / pop-out -------------------------------
    def _sim_dir(self):
        # the last import folder, else the repo's sim_data folder
        if self._last_sim_dir and os.path.isdir(self._last_sim_dir):
            return self._last_sim_dir
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        d = os.path.join(repo_root, "sim_data")
        return d if os.path.isdir(d) else repo_root

    def import_sim(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Import ngspice simulation", self._sim_dir(),
            "ngspice output (*.txt);;All files (*)")
        if path:
            self.import_sim_file(path)

    def import_sim_file(self, path):
        """Load an ngspice S-parameter table from `path` and overlay it; returns
        True on success.  Shared by the Import button and by auto-import after a
        successful Xschem run."""
        try:
            self._sim = io.load_ngspice_sim(path)
        except Exception as exc:                          # noqa: BLE001
            self._sim = None
            QtWidgets.QMessageBox.warning(
                self, "Import failed",
                f"Could not read this simulation file:\n{exc}")
            return False
        self._last_sim_dir = os.path.dirname(path)
        self._render()
        return True

    def reset(self):
        """Return the plot view to its freshly-opened state: no simulation overlay,
        plots docked, and the trace selectors back to their defaults on the next
        update (the caller recomputes)."""
        if self._popout is not None:
            self._dock_back(None)
        self._sim = None
        self._last_sim_dir = ""
        self._prev_aux = None          # force the trace selectors back to defaults

    def export_csv(self):
        if not self._last:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export response data", "snp2le_response.csv", "CSV (*.csv)")
        if not path:
            return
        cols = list(self._last.keys())
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(cols)
            w.writerows(zip(*[self._last[c] for c in cols]))

    def toggle_popout(self):
        if self._popout is None:
            size = self._content.size()                    # keep the mounted size
            self._popout = QtWidgets.QMainWindow(self)
            self._popout.setWindowTitle("Plots")
            from .logo import logo_icon
            self._popout.setWindowIcon(logo_icon())
            self._popout.setCentralWidget(self._content)   # whole panel, incl. controls
            self._popout.resize(size)
            self._popout.closeEvent = self._dock_back
            self._popout.show()
            self.popout_btn.setText("Dock plots")
            self.popped_out.emit()
        else:
            self._dock_back(None)

    def _dock_back(self, _event):
        if self._popout is not None:
            self.layout().addWidget(self._content)
            popout, self._popout = self._popout, None
            popout.deleteLater()
            self.popout_btn.setText("Pop out plots")
            self.docked.emit()
