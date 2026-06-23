"""main_window.py - assembles the UI and is the controller."""
from __future__ import annotations
import os
import time
from PySide6 import QtCore, QtWidgets

from core.state import ConverterState
from core import io, engine, netlist, xschem

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
        # Preferred size, but never larger than the screen: on a small laptop a fixed
        # 1500x940 would open off-screen with clipped controls.  availableGeometry()
        # excludes the taskbar and is in logical px (Qt already does the DPI scaling),
        # so we clamp to ~92% of it and centre the window.
        screen = QtWidgets.QApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail is not None:
            w = min(1500, int(avail.width() * 0.92))
            h = min(940, int(avail.height() * 0.92))
            self.resize(w, h)
            self.move(avail.x() + (avail.width() - w) // 2,
                      avail.y() + (avail.height() - h) // 2)
        else:
            self.resize(1500, 940)

        self.state = ConverterState()
        # seed with a bundled example; fall back to the synthetic demo
        self._examples_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "examples")
        self._last_export_dir = {}        # per-dialect remembered export folder
        self._sch_path = ""               # selected Xschem testbench
        self._last_sch_dir = ""           # remembered .sch folder
        self._sim_proc = None             # running xschem QProcess
        self._sim_start = 0.0             # when the current run started (for auto-import)
        self._sim_timer = None            # polls sim_data for the result after a run
        self._sim_last_output = ""        # captured xschem/ngspice output (for diagnostics)
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
        self.top.export_clicked.connect(self.on_export)
        self.top.load_sch_clicked.connect(self.on_load_sch)
        self.top.run_sim_clicked.connect(self.on_run_sim)
        self.top.reset_clicked.connect(self.on_reset)
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
        self.state.f_extract = v["f_extract"]
        self.state.n_segments = v["n_segments"]
        self.state.iso_resistor = v["iso_resistor"]
        self.state.max_order = v["max_order"]
        self.state.enforce_passivity = v["enforce_passivity"]

    def on_change(self):
        self._pull()
        self._timer.start()

    def on_view_change(self, view):
        self.stack.setCurrentIndex(0 if view == "design" else 1)

    def _cancel_sim(self):
        """Stop any running / pending simulation (run or auto-import) without firing
        its handlers, and free the Run button - e.g. so a new testbench can be run
        while an earlier import is still pending ('Importing…')."""
        self._stop_sim_timer()
        if self._sim_proc is not None:
            try:
                self._sim_proc.finished.disconnect()
                self._sim_proc.errorOccurred.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._sim_proc.kill()
        self._reset_run_button()                  # 'Run Simulation', enabled, proc None

    def on_reset(self):
        """Restore the whole application to its freshly-opened state."""
        self._cancel_sim()                        # stop any running / pending simulation
        # controls -> defaults (also unticks 'Show output', clears the status)
        self.top.reset_controls()
        # drop the simulation overlay and any popped-out plot window
        self.plots.reset()
        # forget the selected testbench
        self._sch_path = ""
        self._last_sch_dir = ""
        if xschem.available():
            self.top.load_sch.setToolTip("")
            self.top.run_sim.setToolTip("")
        # reload the bundled example, exactly as on launch
        self.state = ConverterState()
        self._pull()                              # sync state from the reset controls
        example = os.path.join(self._examples_dir, "blc_ihp-sg13g2.s4p")
        try:
            self.net = io.load_touchstone(example)
            self.state.source_path = example
        except Exception:                         # noqa: BLE001
            self.net = io.demo_network()
        self.top.set_ports(self.net.nports)
        self.top.set_view("design")
        self.recompute()

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
        self.top.set_ports(self.net.nports)   # may auto-switch the structure to fit
        self._pull()                          # sync state from the (re-fitted) controls
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
        ext = "inc" if dialect == "vacask" else "spice"   # VACASK include file (.inc)
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

    # ---- Xschem testbench -------------------------------------------------
    def _xschem_tb_dir(self):
        # the last .sch folder, else the repo's testbenches/xschem folder
        if self._last_sch_dir and os.path.isdir(self._last_sch_dir):
            return self._last_sch_dir
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        d = os.path.join(repo_root, "testbenches", "xschem")
        return d if os.path.isdir(d) else repo_root

    def on_load_sch(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load Xschem testbench", self._xschem_tb_dir(),
            "Xschem schematic (*.sch);;All files (*)")
        if not path:
            return
        self._cancel_sim()                 # free the Run button if a run/import is pending
        self.top.clear_sim_status()        # clear the previous run's outcome label
        self._sch_path = path
        self._last_sch_dir = os.path.dirname(path)
        tb = os.path.basename(path)
        self.top.set_simulator("vacask" if "vacask" in tb.lower() else "ngspice")
        self.top.load_sch.setToolTip(f"Testbench: {tb}")
        self.top.run_sim.setToolTip(f"Run testbench: {tb}")

    def on_run_sim(self):
        if not xschem.available():
            return
        if not self._sch_path:
            QtWidgets.QMessageBox.information(
                self, "Run simulation", "Load a .sch testbench first.")
            return
        self._stop_sim_timer()                            # cancel any pending poll
        self.top.clear_sim_status()                       # reset the outcome label
        sim = self.top.simulator.currentData()            # 'ngspice' | 'vacask'
        show = self.top.sim_output.isChecked()
        prog, args, cwd = xschem.simulate_command(
            self._sch_path, show_output=show, simulator=sim)
        os.makedirs(os.path.join(cwd, "simulations"), exist_ok=True)
        self._sim_proc = QtCore.QProcess(self)
        self._sim_proc.setWorkingDirectory(cwd)
        self._sim_proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        if sim == "vacask" and show:                      # let the postprocess show plots
            env = QtCore.QProcessEnvironment.systemEnvironment()
            env.insert("SHOW_PLOTS", "1")
            self._sim_proc.setProcessEnvironment(env)
        self._sim_proc.finished.connect(self._on_sim_finished)
        self._sim_proc.errorOccurred.connect(self._on_sim_error)
        self._sim_start = time.time()                     # to locate the result file
        self.top.run_sim.setEnabled(False)
        self.top.run_sim.setText("Running…")
        self._sim_proc.start(prog, args)

    def _reset_run_button(self):
        self.top.run_sim.setText("Run Simulation")
        self.top.run_sim.setEnabled(True)
        self._sim_proc = None

    def _sim_output_dir(self):
        # the testbench writes its result here, named after the testbench
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(repo_root, "sim_data")

    # extensions that are never an ngspice data table (binary raw, netlists, logs)
    _NON_DATA_EXTS = (".raw", ".spice", ".inc", ".cir", ".net", ".log", ".out",
                      ".svg", ".png", ".ps", ".pdf", ".sch")
    _DATA_EXTS = (".txt", ".data", ".dat", ".csv")

    def _find_sim_result(self, tb_stem):
        """Locate the simulation result for testbench `tb_stem` in sim_data.

        The testbench writes its result there named after itself.  Prefer a file
        written during this run (newer than the run start) whose name starts with the
        testbench stem - accepting any data-style extension, since `wrdata` targets
        vary (.txt / .data / no extension).  Falls back to the newest fresh data file
        if the naming differs."""
        d = self._sim_output_dir()
        if not os.path.isdir(d):
            return None
        named, data = [], []
        for f in os.listdir(d):
            ext = os.path.splitext(f)[1].lower()
            if ext in self._NON_DATA_EXTS:
                continue
            p = os.path.join(d, f)
            try:
                mt = os.path.getmtime(p)
            except OSError:
                continue
            if mt < self._sim_start - 1:             # not written during this run
                continue
            if f.startswith(tb_stem):                # named after the testbench
                named.append((mt, p))
            elif ext in self._DATA_EXTS:             # fallback: any obvious data file
                data.append((mt, p))
        pool = named or data
        return max(pool)[1] if pool else None        # newest of the matching files

    def _on_sim_finished(self, code, _status):
        out = bytes(self._sim_proc.readAll()).decode(errors="replace") if self._sim_proc else ""
        self._sim_last_output = out                  # keep for the no-result diagnostic
        tb = os.path.basename(self._sch_path)
        if code != 0:
            self._reset_run_button()
            self.top.set_sim_status("failed!", False)
            QtWidgets.QMessageBox.warning(
                self, "Run simulation",
                f"xschem exited with code {code}.\n\n{out[-1500:]}")
            return
        # xschem can launch ngspice in its own window and return before the result is
        # (re)written, so the file may be absent or stale right now.  Poll sim_data
        # until the testbench's output is freshly written, then auto-import it.
        self._sim_poll_stem = os.path.splitext(tb)[0]
        self._sim_poll_deadline = time.time() + 60.0
        self._sim_poll_last = None
        self.top.run_sim.setText("Importing…")
        self.top.run_sim.setEnabled(False)
        self._sim_timer = QtCore.QTimer(self)
        self._sim_timer.setInterval(300)
        self._sim_timer.timeout.connect(self._poll_sim_result)
        self._sim_timer.start()
        self._poll_sim_result()                      # also check immediately

    def _poll_sim_result(self):
        result = self._find_sim_result(self._sim_poll_stem)
        if result is not None:
            try:
                size = os.path.getsize(result)
            except OSError:
                size = -1
            if size > 0 and self._sim_poll_last == (result, size):
                self._finish_sim_import(result)      # seen twice, size settled -> import
                return
            self._sim_poll_last = (result, size)     # let it settle for one more tick
        if time.time() >= self._sim_poll_deadline:   # give up waiting
            self._stop_sim_timer()
            self._reset_run_button()
            if result is not None:
                self._finish_sim_import(result)      # import what we have
            else:
                self.top.set_sim_status("failed!", False)
                log = (self._sim_last_output or "").strip()
                QtWidgets.QMessageBox.information(
                    self, "Run simulation",
                    f"Simulation of {os.path.basename(self._sch_path)} finished, but no "
                    f"fresh result appeared in:\n{self._sim_output_dir()}\n\n"
                    "Use 'Import simulation' to load it manually."
                    + (f"\n\n--- xschem / ngspice output ---\n{log[-1500:]}" if log else ""))

    def _finish_sim_import(self, result):
        self._stop_sim_timer()
        self._reset_run_button()
        if self.plots.import_sim_file(result):       # shows its own warning on failure
            self.top.set_sim_status("successful!", True)
            self.top.set_view("plot")                # reveal the overlay
            QtWidgets.QMessageBox.information(
                self, "Run simulation",
                f"Simulation of {os.path.basename(self._sch_path)} finished and imported "
                f"{os.path.basename(result)} into the plots.")
        else:
            self.top.set_sim_status("failed!", False)

    def _stop_sim_timer(self):
        if self._sim_timer is not None:
            self._sim_timer.stop()
            self._sim_timer = None

    def _on_sim_error(self, _err):
        if self._sim_proc is None:
            return                       # already handled by finished
        self._reset_run_button()
        self.top.set_sim_status("failed!", False)
        QtWidgets.QMessageBox.warning(
            self, "Run simulation", "Could not launch xschem.")

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
        if res.mode == "structure":            # mirror the freq actually used (it may
            self.top.show_fext(res.metrics.get("f_extract"))   # have been auto-detected)
        self.design.update_results(res)
        self.plots.update_results(res)
