"""plot_view.py - the "Plot" page.

Four S-parameters are shown side by side.  Each column shows Magnitude (dB, top)
and Phase (deg, bottom) of one selected S_ij; the four selectors default to the
2-port set S11/S21/S12/S22.  Each curve overlays the loaded data (dashed grey)
against the fitted/extracted model (blue).  Plots pop out and export to CSV.
"""
from __future__ import annotations
import csv
import numpy as np
from PySide6 import QtCore, QtWidgets
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT

from .style import JKU_BLUE, JKU_GRAY

DATA, MODEL = JKU_GRAY, JKU_BLUE
SIDES = ["A", "B", "C", "D"]
DEFAULTS = ["S11", "S21", "S12", "S22"]

_TB_QSS = """
QToolBar { background:transparent; border:none; spacing:1px; }
QToolButton { background:transparent; border:none; padding:2px; border-radius:4px;
    color:#000000; font-size:13px; font-weight:700; min-width:16px; }
QToolButton:hover { background:#e7ecf3; }
"""


class _MiniToolbar(NavigationToolbar2QT):
    toolitems = [t for t in NavigationToolbar2QT.toolitems
                 if t[0] in ("Home", "Pan", "Zoom", "Save")]


def _panel(title):
    frame = QtWidgets.QFrame(); frame.setProperty("class", "panel")
    lay = QtWidgets.QVBoxLayout(frame); lay.setContentsMargins(8, 5, 8, 6); lay.setSpacing(1)
    header = QtWidgets.QHBoxLayout()
    head = QtWidgets.QLabel(title); head.setProperty("class", "panelTitle")
    header.addWidget(head); header.addStretch(1)
    fig = Figure(figsize=(2.7, 2.4)); fig.patch.set_facecolor("white")
    canvas = FigureCanvas(fig); ax = fig.add_subplot(111)
    tb = _MiniToolbar(canvas, frame, coordinates=False)
    tb.setIconSize(QtCore.QSize(15, 15)); tb.setStyleSheet(_TB_QSS)
    header.addWidget(tb)
    lay.addLayout(header); lay.addWidget(canvas, 1)
    return frame, fig, ax, canvas, head


class PlotView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 0); root.setSpacing(8)

        bar = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Results"); title.setProperty("class", "panelTitle")
        bar.addWidget(title); bar.addSpacing(12)
        bar.addWidget(self._hint("S-parameters"))
        self.selectors = []
        for d in DEFAULTS:
            cb = QtWidgets.QComboBox(); cb.setFixedWidth(74)
            cb.currentIndexChanged.connect(self._render)
            self.selectors.append(cb); bar.addWidget(cb)
        bar.addSpacing(14)
        for name, color in [("data", DATA), ("model", MODEL)]:
            sw = QtWidgets.QLabel("\u2014\u2014"); sw.setStyleSheet(f"color:{color};font-weight:700;")
            bar.addWidget(sw); bar.addWidget(self._hint(name)); bar.addSpacing(8)
        bar.addStretch(1)
        self.export_btn = QtWidgets.QPushButton("Export CSV")
        self.popout_btn = QtWidgets.QPushButton("Pop out plots"); self.popout_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.export_csv)
        self.popout_btn.clicked.connect(self.toggle_popout)
        bar.addWidget(self.export_btn); bar.addWidget(self.popout_btn)
        root.addLayout(bar)

        self.grid_host = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(self.grid_host)
        grid.setContentsMargins(0, 0, 0, 0); grid.setSpacing(10)
        self._panels = {}
        for col, side in enumerate(SIDES):
            for row, (kind, t) in enumerate((("mag", "Magnitude  (dB)"),
                                             ("ph", "Phase  (deg)"))):
                frame, fig, ax, canvas, head = _panel(t)
                self._panels[kind + side] = (fig, ax, canvas, head)
                grid.addWidget(frame, row, col)
        for c in range(len(SIDES)):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch(0, 1); grid.setRowStretch(1, 1)
        root.addWidget(self.grid_host, 1)

        self._popout = None
        self._res = None
        self._last = None

    def _hint(self, text):
        lab = QtWidgets.QLabel(text); lab.setProperty("class", "hint")
        return lab

    # ---- entry point -----------------------------------------------------
    def update_results(self, res):
        self._res = res
        n = res.n_ports or 0
        items = [(f"S{i+1}{j+1}", (i, j)) for i in range(n) for j in range(n)]
        for combo, default in zip(self.selectors, DEFAULTS):
            cur = combo.currentText()
            combo.blockSignals(True); combo.clear()
            for text, data in items:
                combo.addItem(text, data)
            idx = combo.findText(cur) if cur else -1
            if idx < 0:
                idx = combo.findText(default)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
            combo.blockSignals(False)
        self._render()

    def _render(self, *_):
        res = self._res
        for _, (_, ax, _, _) in self._panels.items():
            ax.clear()
        if res is None or res.data_s is None or res.model_s is None:
            for _, (fig, _, canvas, _) in self._panels.items():
                canvas.draw_idle()
            return
        f = np.asarray(res.freq, dtype=float); fg = f / 1e9
        self._last = {"f_Hz": f}
        for side, combo in zip(SIDES, self.selectors):
            ij = combo.currentData()
            if ij is None:
                continue
            i, j = ij
            sij = combo.currentText()
            d = np.asarray(res.data_s)[:, i, j]
            m = np.asarray(res.model_s)[:, i, j]
            mag_d = 20 * np.log10(np.maximum(np.abs(d), 1e-12))
            mag_m = 20 * np.log10(np.maximum(np.abs(m), 1e-12))
            ph_d = np.unwrap(np.angle(d)) * 180 / np.pi
            ph_m = np.unwrap(np.angle(m)) * 180 / np.pi

            _, axm, _, headm = self._panels["mag" + side]
            axm.plot(fg, mag_d, color=DATA, ls="--", lw=1.3)
            axm.plot(fg, mag_m, color=MODEL, ls="-", lw=1.6)
            axm.set_xlabel("f (GHz)", fontsize=8); axm.set_ylabel("|S| (dB)", fontsize=8)
            axm.grid(True, alpha=0.3)
            headm.setText(f"Magnitude (dB) \u00b7 {sij}")

            _, axp, _, headp = self._panels["ph" + side]
            axp.plot(fg, ph_d, color=DATA, ls="--", lw=1.3)
            axp.plot(fg, ph_m, color=MODEL, ls="-", lw=1.6)
            axp.set_xlabel("f (GHz)", fontsize=8); axp.set_ylabel("phase (deg)", fontsize=8)
            axp.grid(True, alpha=0.3)
            headp.setText(f"Phase (deg) \u00b7 {sij}")

            self._last[f"{sij}|data_dB"] = mag_d
            self._last[f"{sij}|model_dB"] = mag_m
            self._last[f"{sij}|data_deg"] = ph_d
            self._last[f"{sij}|model_deg"] = ph_m

        for _, (fig, _, canvas, _) in self._panels.items():
            fig.tight_layout(pad=0.4); canvas.draw_idle()

    # ---- CSV / pop-out ---------------------------------------------------
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
            self._popout = QtWidgets.QMainWindow(self)
            self._popout.setWindowTitle("snp2le \u2014 Plots")
            self._popout.setCentralWidget(self.grid_host)
            self._popout.resize(1320, 720)
            self._popout.closeEvent = self._dock_back
            self._popout.show()
            self.popout_btn.setText("Dock plots")
        else:
            self._dock_back(None)

    def _dock_back(self, _event):
        if self._popout is not None:
            self.layout().addWidget(self.grid_host, 1)
            popout, self._popout = self._popout, None
            popout.deleteLater()
            self.popout_btn.setText("Pop out plots")
