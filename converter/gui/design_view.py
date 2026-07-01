"""design_view.py - the "Design & Schematic" page.

Left: a "Conversion" panel with the loaded-file header, the fit/extraction result
(RMS, passivity, order/Q), and the element-values table.  Right: the schematic
panel (drawn for physical models, a note for the universal macromodel) above the
netlist panel (ngspice / VACASK tabs with export buttons).
"""
from __future__ import annotations
from PySide6 import QtCore, QtWidgets

from core.units import format_eng
from .widgets import OutputField, section_title, MathLabel, passivity_text
from .schematic_widget import SchematicWidget


def _panel(title):
    frame = QtWidgets.QFrame(); frame.setProperty("class", "panel")
    lay = QtWidgets.QVBoxLayout(frame)
    lay.setContentsMargins(16, 12, 16, 12); lay.setSpacing(6)
    if title:
        head = QtWidgets.QLabel(title); head.setProperty("class", "panelTitle")
        lay.addWidget(head)
    return frame, lay


class DesignView(QtWidgets.QWidget):
    save_clicked = QtCore.Signal()
    load_clicked = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QtWidgets.QHBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 0); root.setSpacing(12)

        # ---- left: conversion panel --------------------------------------
        self.left_frame, left = _panel(None)
        self.left_frame.setFixedWidth(430)
        header = QtWidgets.QHBoxLayout()
        t = QtWidgets.QLabel("Conversion"); t.setProperty("class", "panelTitle")
        self.load_btn = QtWidgets.QPushButton("Load design"); self.load_btn.setFixedHeight(30)
        self.save_btn = QtWidgets.QPushButton("Save design"); self.save_btn.setObjectName("primary")
        self.save_btn.setFixedHeight(30)
        self.load_btn.clicked.connect(self.load_clicked.emit)
        self.save_btn.clicked.connect(self.save_clicked.emit)
        header.addWidget(t); header.addStretch(1)
        header.addWidget(self.load_btn); header.addWidget(self.save_btn)
        left.addLayout(header)

        self.file_lbl = QtWidgets.QLabel("No file loaded")
        self.file_lbl.setProperty("class", "hint"); self.file_lbl.setWordWrap(True)
        left.addWidget(self.file_lbl)

        left.addWidget(section_title("Result"))
        # label_w fits the widest label ("ext. frequency") so the values stay aligned
        self.mode_out = OutputField("mode", "\u2014", label_w=100, equals=False)
        self.rms_out = OutputField("RMS error", "\u2014", label_w=100, equals=False)
        self.pass_out = OutputField("passivity", "\u2014", label_w=100, equals=False)
        self.order_out = OutputField("order / Q", "\u2014", label_w=100, equals=False)
        for w in (self.mode_out, self.rms_out, self.pass_out, self.order_out):
            left.addWidget(w)

        left.addWidget(section_title("Element values"))
        self.values_host = QtWidgets.QVBoxLayout(); self.values_host.setSpacing(4)
        left.addLayout(self.values_host)

        self.tol_title = section_title("Tolerances")
        left.addWidget(self.tol_title)
        self.tol_caption = QtWidgets.QLabel(
            "± tolerance at the ext. frequency (the ○ marker on the model curve): "
            "|data − model| / model.")
        self.tol_caption.setStyleSheet("color:#7d828c;font-size:10px;")
        self.tol_caption.setWordWrap(True)
        self.tol_caption.setToolTip(
            "At the ext. frequency (the ○ marker on the model curve), the parameter the "
            "measured data implies is compared to the model value:\n\n"
            "    tolerance = |value − model| / |model| × 100\n\n"
            "Directly-read reciprocal terms (e.g. the series L, R) read 0 %, since the model "
            "reproduces them exactly. Terms the model must approximate (e.g. the shunt C "
            "forced equal across two slightly asymmetric ports) carry the residual it "
            "cannot fit. Frequency dispersion away from the ext. frequency is visible in "
            "the plots.")
        left.addWidget(self.tol_caption)
        self.tol_host = QtWidgets.QVBoxLayout(); self.tol_host.setSpacing(4)
        left.addLayout(self.tol_host)

        self.msg_lbl = QtWidgets.QLabel("")
        self.msg_lbl.setStyleSheet("color:#7d828c;font-size:10px;"); self.msg_lbl.setWordWrap(True)
        left.addWidget(self.msg_lbl)
        left.addStretch(1)
        root.addWidget(self.left_frame)

        # ---- right: schematic + netlist ----------------------------------
        right = QtWidgets.QVBoxLayout(); right.setSpacing(12)
        sch_frame, sch_lay = _panel("Schematic")
        self.schematic = SchematicWidget(); sch_lay.addWidget(self.schematic, 1)
        right.addWidget(sch_frame, 3)

        net_frame, net_lay = _panel("Netlist")
        self.tabs = QtWidgets.QTabWidget()
        self.ngspice_edit = QtWidgets.QPlainTextEdit(); self.ngspice_edit.setReadOnly(True)
        self.vacask_edit = QtWidgets.QPlainTextEdit(); self.vacask_edit.setReadOnly(True)
        self.tabs.addTab(self.ngspice_edit, "Ngspice (SPICE)")
        self.tabs.addTab(self.vacask_edit, "VACASK (Spectre)")
        self.tabs.setCurrentIndex(0)
        net_lay.addWidget(self.tabs, 1)
        right.addWidget(net_frame, 4)
        root.addLayout(right, 1)

    # ---- update ----------------------------------------------------------
    def set_file_info(self, text):
        self.file_lbl.setText(text)

    def _clear(self, host):
        while host.count():
            it = host.takeAt(0)
            w = it.widget()
            if w:
                w.setParent(None)          # synchronous removal (no overlap)
                w.deleteLater()

    @staticmethod
    def _tol_color(pct):
        if pct < 2.0:
            return "#2e7d32"               # green: model fits this value at f_ext
        if pct < 10.0:
            return "#b8860b"               # amber: moderate residual
        return "#d95c4c"                   # red: the model cannot fit this term

    @staticmethod
    def _tol_text(pct):
        if pct != pct:                     # NaN: not defined for this value
            return "n/a", "#7d828c"
        if pct > 100.0:                    # value not stable in the operating band
            return ">100%", "#d95c4c"
        return f"±{pct:.1f}%", DesignView._tol_color(pct)

    def update_results(self, res):
        self.mode_out.set_value("universal" if res.mode == "universal"
                                else "structure")
        if res.rms_error == res.rms_error:               # not NaN
            self.rms_out.set_value(f"{res.rms_error:.2e}")
        else:
            self.rms_out.set_value("\u2014")
        self.pass_out.set_value(passivity_text(res))
        if res.mode == "universal":
            self.order_out.label.setText("order")
            self.order_out.set_value(f"{res.n_poles} poles")
        else:                                             # structure: extraction freq used
            f_ext = res.metrics.get("f_extract")
            self.order_out.label.setText("ext. frequency")
            self.order_out.set_value(format_eng(f_ext, "Hz") if f_ext else "\u2014")

        self._clear(self.values_host)
        if not res.ok:
            lab = QtWidgets.QLabel(res.error)
            lab.setStyleSheet("color:#d95c4c;"); lab.setWordWrap(True)
            self.values_host.addWidget(lab)
        elif res.physical and res.value_rows:
            for label, val, unit in res.value_rows:
                of = OutputField(label, format_eng(val, unit), label_w=52,
                                 equals=True, field_w=128)
                self.values_host.addWidget(of, alignment=QtCore.Qt.AlignHCenter)
        else:
            n_el = len(res.ir.elements) if res.ir else 0
            note = QtWidgets.QLabel(
                f"macromodel: {n_el} elements (R / C + controlled sources).\n"
                "Electrically exact, not physically interpretable.")
            note.setStyleSheet("color:#7d828c;font-size:11px;"); note.setWordWrap(True)
            self.values_host.addWidget(note)
            dc = getattr(res, "dc", None)                 # DC operating-point health
            if dc is not None:
                mark = "✓" if dc.ok else "⚠"
                color = "#3a8a5c" if dc.ok else "#d95c4c"
                state = "solvable" if dc.ok else "may be SINGULAR"
                dc_lbl = QtWidgets.QLabel(
                    f"{mark}  DC operating point {state}  (margin {dc.margin:.0e})")
                dc_lbl.setStyleSheet(f"color:{color};font-size:11px;")
                dc_lbl.setWordWrap(True)
                self.values_host.addWidget(dc_lbl)

        # ---- Tolerances: per-element band drift around f_ext (structures) ----
        self._clear(self.tol_host)
        drift = res.value_drift if (res.ok and res.physical) else {}
        rows = [(lab, drift[lab]) for lab, _, _ in res.value_rows
                if lab in drift] if res.physical else []
        show_tol = bool(rows)
        self.tol_title.setVisible(show_tol)
        self.tol_caption.setVisible(show_tol)
        for lab, pct in rows:
            text, color = self._tol_text(pct)
            of = OutputField(lab, text, label_w=52, equals=True, field_w=128)
            of.value.setStyleSheet(f"color:{color};")
            self.tol_host.addWidget(of, alignment=QtCore.Qt.AlignHCenter)

        self.msg_lbl.setText("  \u00b7  ".join(res.messages) if res.messages else "")
        self.ngspice_edit.setPlainText(res.ngspice or "")
        self.vacask_edit.setPlainText(res.vacask or "")

        # schematic
        if not res.ok:
            self.schematic.show_message(f"\u26a0  {res.error}")
        elif res.physical and getattr(res, "_structure", None) is not None:
            try:
                self.schematic.show_drawing(res._structure.schematic_drawing(res.ir))
            except Exception as exc:                     # noqa: BLE001
                self.schematic.show_message(f"(schematic failed: {exc})")
        else:
            self.schematic.show_message(
                "Universal macromodel\n\nThe vector-fitted network is a state-space "
                "realization (R / C + controlled sources),\nwhich has no human-readable "
                "schematic.\nSee the netlist below.")
