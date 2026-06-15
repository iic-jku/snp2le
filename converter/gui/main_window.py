"""main_window.py - assembles the UI and is the controller."""
from __future__ import annotations
from PySide6 import QtCore, QtWidgets

from core.state import ConverterState
from core import io, engine

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
        self.net = io.demo_network()          # seed with a demo 2-port

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
        self.state.pdk = v["pdk"]
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
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Touchstone file", "",
            "Touchstone (*.s1p *.s2p *.s3p *.s4p *.snp *.ts);;All files (*)")
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

    def on_export(self, dialect):
        res = engine.convert(self.state, self.net)
        text = res.vacask if dialect == "vacask" else res.ngspice
        ext = "scs" if dialect == "vacask" else "cir"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, f"Export {dialect} netlist", f"s_equivalent.{ext}",
            f"Netlist (*.{ext});;All files (*)")
        if path:
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
        self.recompute()

    # ---- the pipeline ----------------------------------------------------
    def recompute(self):
        self.design.set_file_info(io.info_for(self.net).summary)
        res = engine.convert(self.state, self.net)
        self.design.update_results(res)
        self.plots.update_results(res)
