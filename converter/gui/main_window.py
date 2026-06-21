"""main_window.py - assembles the UI and is the controller."""
from __future__ import annotations
import os
from PySide6 import QtCore, QtWidgets

from core.state import ConverterState
from core import io, engine, netlist

from .top_bar import TopBar
from .design_view import DesignView
from .plot_view import PlotView
from .help_dialog import HelpDialog
from .footer import Footer


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("S-Parameter To Lumped Element Netlist Converter")
        from .logo import logo_icon
        self.setWindowIcon(logo_icon())
        self.resize(1500, 940)

        self.state = ConverterState()
        # seed with a bundled example; fall back to the synthetic demo
        self._examples_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "examples")
        self._last_export_dir = {}        # per-dialect remembered export folder
        example = os.path.join(self._examples_dir, "blc_ihp-sg13g2.s4p")
        try:
            self.net = io.load_touchstone(example)
            self.state.source_path = example
        except Exception:                     # noqa: BLE001
            self.net = io.demo_network()

        root = QtWidgets.QWidget(); root.setObjectName("root")
        lay = QtWidgets.QVBoxLayout(root); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.top = TopBar()
        self.stack = QtWidgets.QStackedWidget()
        self.design = DesignView()
        self.plots = PlotView()
        self.stack.addWidget(self.design); self.stack.addWidget(self.plots)
        lay.addWidget(self.top); lay.addWidget(self.stack, 1)
        self.footer = Footer(); lay.addWidget(self.footer)
        self.setCentralWidget(root)

        self._timer = QtCore.QTimer(self); self._timer.setSingleShot(True)
        self._timer.setInterval(120); self._timer.timeout.connect(self.recompute)

        self._wire()
        self.top.set_ports(self.net.nports)
        self.recompute()

    def _wire(self):
        self.top.changed.connect(self.on_change)
        self.top.view_changed.connect(self.on_view_change)
        self.top.help_clicked.connect(self.on_help)
        self.top.load_clicked.connect(self.on_load_snp)
        self.design.export_clicked.connect(self.on_export)
        self.design.save_clicked.connect(self.on_save_design)
        self.design.load_clicked.connect(self.on_load_design)
        # pop the plots out -> show Design view; dock them back -> return to Plot
        self.plots.popped_out.connect(lambda: self.top.set_view("design"))
        self.plots.docked.connect(lambda: self.top.set_view("plot"))

    # ---- state sync ------------------------------------------------------
    def _pull(self):
        v = self.top.values()
        self.state.mode = v["mode"]
        self.state.structure_key = v["structure_key"]
        self.state.max_order = v["max_order"]
        self.state.enforce_passivity = v["enforce_passivity"]

    def on_change(self):
        self._pull()
        self._timer.start()

    def on_view_change(self, view):
        self.stack.setCurrentIndex(0 if view == "design" else 1)

    def on_help(self):
        HelpDialog(self).exec()

    # ---- file loading ----------------------------------------------------
    def on_load_snp(self):
        # start in the folder of the last loaded file, else the examples folder
        start_dir = self._examples_dir
        if self.state.source_path:
            last = os.path.dirname(self.state.source_path)
            if os.path.isdir(last):
                start_dir = last
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Touchstone file", start_dir,
            "Touchstone (*.s1p *.s2p *.s3p *.s4p *.s5p *.s6p *.s7p *.s8p "
            "*.snp *.ts);;All files (*)")
        if not path:
            return
        try:
            self.net = io.load_touchstone(path)
            self.state.source_path = path
        except Exception as exc:                          # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "Load failed",
                                          f"Could not load this file:\n{exc}")
            return
        self.top.set_ports(self.net.nports)
        self.recompute()

    def _export_dir(self, dialect):
        # last folder for this dialect, else netlist/spectre (vacask) or
        # netlist/spice (ngspice) at the repo root
        last = self._last_export_dir.get(dialect)
        if last and os.path.isdir(last):
            return last
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        sub = "spectre" if dialect == "vacask" else "spice"
        default = os.path.join(repo_root, "netlist", sub)
        os.makedirs(default, exist_ok=True)
        return default

    def on_export(self, dialect):
        res = engine.convert(self.state, self.net)
        ext = "scs" if dialect == "vacask" else "spice"
        # default name: <source>_le, falling back to the subcircuit's own name
        src = os.path.splitext(os.path.basename(self.state.source_path))[0] \
            if self.state.source_path else ""
        name = f"{src + '_le' if src else (res.ir.name if res.ir else 's_equivalent')}.{ext}"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, f"Export {dialect} netlist",
            os.path.join(self._export_dir(dialect), name),
            f"Netlist (*.{ext});;All files (*)")
        if not path:
            return
        self._last_export_dir[dialect] = os.path.dirname(path)   # remember per dialect
        if res.ir is not None:
            # name the .SUBCKT after the chosen file, e.g. bpf_le.spice -> bpf_le
            res.ir.name = netlist.safe_subckt_name(
                os.path.splitext(os.path.basename(path))[0])
            text = (netlist.render_vacask(res.ir) if dialect == "vacask"
                    else netlist.render_ngspice(res.ir))
        else:
            text = res.vacask if dialect == "vacask" else res.ngspice
        with open(path, "w") as fh:
            fh.write(text)

    def on_save_design(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save conversion settings", "snp2le.json", "JSON (*.json)")
        if path:
            with open(path, "w") as fh:
                fh.write(self.state.to_json())

    def on_load_design(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load conversion settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path) as fh:
                self.state = ConverterState.from_json(fh.read())
        except Exception as exc:                          # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "Load failed", str(exc))
            return
        if self.state.source_path:
            try:
                self.net = io.load_touchstone(self.state.source_path)
                self.top.set_ports(self.net.nports)
            except Exception:                             # noqa: BLE001
                pass
        self.top.set_values(self.state)        # sync the controls to the loaded design
        self.recompute()

    # ---- the pipeline ----------------------------------------------------
    def recompute(self):
        self.design.set_file_info(io.info_for(self.net).summary)
        res = engine.convert(self.state, self.net)
        self.design.update_results(res)
        self.plots.update_results(res)
