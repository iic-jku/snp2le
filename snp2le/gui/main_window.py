"""main_window.py - assembles the UI and is the controller."""
from __future__ import annotations
import os
import time
from PySide6 import QtCore, QtWidgets

from snp2le.core.state import ConverterState
from snp2le.core import io, engine, netlist, xschem

from .top_bar import TopBar
from .design_view import DesignView
from .plot_view import PlotView
from .help_dialog import HelpDialog
from .log_dialog import LogWindow
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
        # seed with a bundled example, or fall back to the synthetic demo
        self._examples_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "examples")
        self._last_export_dir = {}        # per-dialect remembered export folder
        self._sch_path = ""               # selected Xschem testbench
        self._last_sch_dir = ""           # remembered .sch folder
        self._sim_proc = None             # running xschem QProcess
        self._sim_start = 0.0             # when the current run started (for auto-import)
        self._sim_timer = None            # polls sim_data for the result after a run
        self._sim_last_output = ""        # captured xschem/Ngspice output (for diagnostics)
        self._sim_watchdog = None         # hard cap so a stuck run can't pin the Run button
        self._sim_simulator = ""          # 'ngspice' | 'vacask' of the current run
        self._sim_output_buf = ""         # xschem output accumulated live during the run
        self._sim_interactive = False     # 'Show output' run: user-driven, no idle kill
        self._sim_idle_since = 0.0        # last time the run's process tree used CPU
        self._sim_last_cpu = 0.0          # cumulative CPU seconds at the previous check
        self._sim_vacask_seen = False     # a detached vacask process was observed running
        self._sim_vacask_gone_at = 0.0    # when that vacask process disappeared (0 = no)
        self._sim_log_path = None         # VACASK console log (its output is redirected here)
        self._log_win = None              # 'Show output' window that tails the VACASK log
        self._log_timer = None            # refreshes that window while the run is in progress
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
        # pop the plots out -> show Design view. Dock them back -> return to Plot
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
        its handlers, and free the Run button, e.g. so a new testbench can be run
        while an earlier import is still pending ('Importing...')."""
        active = self._sim_proc is not None or self._sim_timer is not None
        self._stop_sim_timer()
        if self._sim_proc is not None:
            try:
                self._sim_proc.finished.disconnect()
                self._sim_proc.errorOccurred.disconnect()
                self._sim_proc.readyRead.disconnect()
            except (RuntimeError, TypeError):
                pass
            self._sim_proc.kill()
        if active and self._sim_simulator == "vacask":   # xschem already exited. The real
            self._kill_vacask()                          # vacask runs detached, so kill it
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
        # remembered folder for this dialect, else the repo's netlist/<dialect> when
        # running from the source tree, else the current working directory (so an
        # installed copy never tries to write inside its site-packages)
        last = self._last_export_dir.get(dialect)
        if last and os.path.isdir(last):
            return last
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        sub = "spectre" if dialect == "vacask" else "spice"
        default = os.path.join(repo_root, "netlist", sub)
        return default if os.path.isdir(default) else os.getcwd()

    def on_export(self, dialect):
        res = engine.convert(self.state, self.net)
        if not res.ok:                                    # no usable netlist to write
            QtWidgets.QMessageBox.warning(
                self, "Export netlist",
                "The current conversion did not succeed, so there is nothing to export:\n"
                f"{res.error}")
            return
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
        raw_stem = os.path.splitext(os.path.basename(path))[0]
        renamed = False
        if res.ir is not None:
            # name the .SUBCKT after the chosen file, e.g. two_port.spice -> two_port
            res.ir.name = netlist.safe_subckt_name(raw_stem)
            if res.ir.name != raw_stem:                  # name had illegal chars: save the
                path = os.path.join(os.path.dirname(path),  # FILE under the valid name too,
                                    res.ir.name + "." + ext)  # so file = subckt = the note
                renamed = True
            text = (netlist.render_vacask(res.ir) if dialect == "vacask"
                    else netlist.render_ngspice(res.ir))
        else:
            text = res.vacask if dialect == "vacask" else res.ngspice
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        # a file name like 'two-port' is not a legal subckt identifier ('-' is the minus
        # operator in SPICE / Spectre), so both the file and the subcircuit were saved
        # under the sanitised name, so tell the user the actual name.
        if renamed:
            QtWidgets.QMessageBox.information(
                self, "Export note",
                f"'{raw_stem}' is not a valid Ngspice / VACASK subcircuit name (for example "
                f"'-' is the subtraction operator), so it was saved as "
                f"'{os.path.basename(path)}' with subcircuit '{res.ir.name}'.\n\n"
                "Instantiate it in your testbench by that name. Tip: use '_' instead of "
                "'-' in the file name to avoid this.")

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

    def _sim_active(self):
        return self._sim_proc is not None or self._sim_timer is not None

    def _stop_sim(self):
        """User-pressed Stop: cancel the run / pending import and mark it stopped."""
        self._cancel_sim()                                # kills xschem, stops the poll, resets
        self.top.set_sim_status("stopped", False)

    def _write_sim_range(self, cwd):
        """Push the loaded Touchstone's frequency span into the testbench sweep.

        Writes sim_range.inc (VACASK: `var f_min/f_max`) and sim_range.spice (Ngspice:
        `.csparam f_min/f_max`) next to the testbench.  The testbench includes the matching
        file (VACASK `include "../sim_range.inc"`, Ngspice `.include ../sim_range.spice`),
        so the f_min/f_max sweep bounds always follow the loaded data, yet the testbench
        still runs standalone in Xschem with the last-written range.  f0 stays in the
        testbench, since it is a design point rather than a sweep bound.  Both `../` includes resolve
        from the netlist dir (cwd/simulations) to cwd, where these files are written."""
        net = getattr(self, "net", None)
        if net is None:
            return
        try:
            xschem.write_sim_range(cwd, float(net.f[0]), float(net.f[-1]))
        except (TypeError, IndexError, ValueError, OSError):
            pass

    def on_run_sim(self):
        if self._sim_active():                            # the button is 'Stop' -> cancel
            self._stop_sim()
            return
        if not xschem.available():
            return
        if not self._sch_path:
            QtWidgets.QMessageBox.information(
                self, "Run simulation", "Load a .sch testbench first.")
            return
        self._stop_sim_timer()                            # cancel any pending poll
        self.top.clear_sim_status()                       # reset the outcome label
        sim = self.top.simulator.currentData()            # 'ngspice' | 'vacask'
        self._sim_simulator = sim
        show = self.top.sim_output.isChecked()
        self._sim_interactive = show                      # Show output: user-driven run
        prog, args, cwd = xschem.simulate_command(
            self._sch_path, show_output=show, simulator=sim)
        self._write_sim_range(cwd)                        # sync testbench sweep to the data
        os.makedirs(os.path.join(cwd, "simulations"), exist_ok=True)
        self._sim_log_path = None
        if sim == "vacask":                               # its console is redirected to a log
            self._sim_log_path = xschem.vacask_log_path(self._sch_path)
            try:
                os.remove(self._sim_log_path)             # drop the previous run's log
            except OSError:
                pass
        self._sim_proc = QtCore.QProcess(self)
        self._sim_proc.setWorkingDirectory(cwd)
        self._sim_proc.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        if sim == "vacask" and show:                      # Show output: tail the console log
            env = QtCore.QProcessEnvironment.systemEnvironment()
            env.insert("SHOW_PLOTS", "1")                 # and let the postprocess pop its plot
            self._sim_proc.setProcessEnvironment(env)
            self._start_log_tail()
        self._sim_proc.finished.connect(self._on_sim_finished)
        self._sim_proc.errorOccurred.connect(self._on_sim_error)
        self._sim_output_buf = ""                         # capture output as it streams, so
        self._sim_proc.readyRead.connect(self._on_sim_readyread)  # the full log is in hand
        self._sim_start = time.time()                     # to locate the result file
        self.top.run_sim.setText("Stop")                  # the run button becomes Stop
        self.top.set_sim_progress("running...")
        self._sim_proc.start(prog, args)
        # Activity watchdog: a real simulation keeps using CPU, while a hung xschem (e.g.
        # stuck at an interactive prompt) goes idle.  So we cap on *inactivity*, not wall
        # clock. A long but busy run is never killed, only a stuck one (see
        # _check_sim_activity).  Falls back to a generous wall-clock cap where /proc is
        # unavailable (e.g. Windows).
        self._sim_idle_since = time.time()
        self._sim_last_cpu = 0.0
        self._sim_watchdog = QtCore.QTimer(self)
        self._sim_watchdog.setInterval(5000)              # check every 5 s
        self._sim_watchdog.timeout.connect(self._check_sim_activity)
        self._sim_watchdog.start()

    def _reset_run_button(self):
        self._stop_log_tail()                             # final log read, stop tailing
        if self._sim_watchdog is not None:                # stop the hard-cap timer
            self._sim_watchdog.stop()
            self._sim_watchdog = None
        self.top.run_sim.setText("Run Simulation")
        self.top.run_sim.setEnabled(True)
        if self._sim_proc is not None:                    # don't accumulate finished
            self._sim_proc.deleteLater()                  # QProcess objects over a session
        self._sim_proc = None

    def _read_vacask_log(self) -> str:
        """The captured VACASK console for this run, or '' if none was written."""
        p = self._sim_log_path
        if p and os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    return fh.read().strip()
            except OSError:
                pass
        return ""

    def _start_log_tail(self):
        """Open the 'Show output' window and refresh it from the VACASK log as it runs."""
        if self._log_win is None:
            self._log_win = LogWindow(self, "VACASK output")
        self._log_win.set_text("(waiting for VACASK to start...)")
        self._log_win.show()
        self._log_win.raise_()
        if self._log_timer is None:
            self._log_timer = QtCore.QTimer(self)
            self._log_timer.setInterval(300)
            self._log_timer.timeout.connect(self._update_log_window)
        self._log_timer.start()

    def _update_log_window(self):
        if self._log_win is None:
            return
        txt = self._read_vacask_log()
        if txt:
            self._log_win.set_text(txt)

    def _stop_log_tail(self):
        if self._log_timer is not None:
            self._log_timer.stop()
        if self._log_win is not None and self._log_win.isVisible():
            self._update_log_window()                     # show whatever landed last

    def _check_sim_activity(self):
        # Runs every 5 s while a run is in progress.  Kill + report failed only when the
        # run is genuinely stuck (idle with no CPU too long, or past a generous absolute
        # cap), so an arbitrarily long but busy simulation is never wrongly killed.
        if self._sim_proc is None:
            return
        now = time.time()
        if self._sim_interactive:                         # Show output: user drives it, so
            if now - self._sim_start > 3600.0:            # never idle-kill, just a 1 h cap
                self._sim_watchdog_fire("the interactive run exceeded the 1 h limit")
            return
        cpu = self._sim_tree_cpu_time()
        if cpu is None:                                   # no /proc -> wall-clock cap
            if now - self._sim_start > 1800.0:
                self._sim_watchdog_fire("the run exceeded the 30 min limit")
            return
        if cpu > self._sim_last_cpu + 0.05:               # tree used CPU since last check
            self._sim_idle_since = now
        self._sim_last_cpu = cpu
        if now - self._sim_idle_since > 60.0:             # 1 min with no CPU -> hung
            self._sim_watchdog_fire("the simulation used no CPU for 60 s (it looks hung)")
        elif now - self._sim_start > 3600.0:              # 1 h absolute backstop
            self._sim_watchdog_fire("the run exceeded the 1 h limit")

    def _sim_tree_cpu_time(self):
        """Cumulative CPU seconds of the xschem process and all its descendants, read
        straight from /proc (no psutil needed).  Returns None where /proc is unavailable
        (e.g. Windows) or on error, so the watchdog falls back to a wall-clock cap."""
        pid = int(self._sim_proc.processId() or 0) if self._sim_proc is not None else 0
        if not pid or not os.path.isdir("/proc"):
            return None
        try:
            ticks = float(os.sysconf("SC_CLK_TCK")) or 100.0
        except (ValueError, OSError, AttributeError):
            ticks = 100.0
        # snapshot every process once: pid -> (ppid, cpu_seconds)
        info = {}
        try:
            live = [int(d) for d in os.listdir("/proc") if d.isdigit()]
        except OSError:
            return None
        for p in live:
            try:
                with open(f"/proc/{p}/stat") as fh:
                    data = fh.read()
                fields = data[data.rfind(")") + 2:].split()   # after 'comm)': state ppid ...
                info[p] = (int(fields[1]), (int(fields[11]) + int(fields[12])) / ticks)
            except (OSError, ValueError, IndexError):
                continue
        if pid not in info:
            return None                                        # xschem already gone
        kids = {}
        for cp, (pp, _) in info.items():
            kids.setdefault(pp, []).append(cp)
        total, stack, seen = 0.0, [pid], set()
        while stack:                                           # xschem + all descendants
            cur = stack.pop()
            if cur in seen or cur not in info:
                continue
            seen.add(cur)
            total += info[cur][1]
            stack.extend(kids.get(cur, ()))
        return total

    def _sim_watchdog_fire(self, reason):
        if self._sim_proc is None:
            return
        try:                                              # keep whatever it printed so far
            self._sim_last_output = bytes(self._sim_proc.readAll()).decode(errors="replace")
        except Exception:                                 # noqa: BLE001
            pass
        self._cancel_sim()                                # kills xschem, stops the poll, resets
        self.top.set_sim_status("failed!", False)
        log = (self._sim_last_output or "").strip()
        QtWidgets.QMessageBox.warning(
            self, "Run simulation",
            f"The simulation was stopped: {reason}.\n\n"
            + (log[-1500:] if log else "(no output was captured)"))

    def _sim_output_dir(self):
        # the testbench writes its result here, named after the testbench
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return os.path.join(repo_root, "sim_data")

    # extensions that are never an Ngspice data table (binary raw, netlists, logs)
    _NON_DATA_EXTS = (".raw", ".spice", ".inc", ".cir", ".net", ".log", ".out",
                      ".svg", ".png", ".ps", ".pdf", ".sch")
    _DATA_EXTS = (".txt", ".data", ".dat", ".csv")

    def _find_sim_result(self, tb_stem):
        """Locate the simulation result for testbench `tb_stem` in sim_data.

        The testbench writes its result there named after itself.  Prefer a file
        written during this run (newer than the run start) whose name starts with the
        testbench stem, accepting any data-style extension, since `wrdata` targets
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

    def _fresh_abort_marker(self, stem):
        """True if this run left a fresh <stem>.aborted marker (the VACASK postprocess
        writes one when the analysis ran but produced no usable data)."""
        p = os.path.join(self._sim_output_dir(), stem + ".aborted")
        try:
            return os.path.getmtime(p) >= self._sim_start - 1
        except OSError:
            return False

    # xschem exits 0 even when the simulator it launched (Ngspice / VACASK) crashes,
    # errors, or aborts an analysis. It only prints the outcome in its output.  Catch
    # every failure phrasing so a clearly-failed run is reported the instant its output
    # reaches us.  This is a fast path only: xschem does not always stream its simulator
    # console to us, so the result-file poll below is the capture-independent fallback.
    _SIM_FAIL_MARKERS = (
        "child process exited abnormally",   # the simulator subprocess crashed
        "Failed: ",                          # xschem: the simulator run failed
        "aborted.",                          # VACASK: "Analysis '...' aborted."
        "Factorization failed",              # VACASK: singular matrix
        "Error running ",                    # xschem: a run / postprocess command failed
    )

    def _sim_reported_failure(self, out):
        return any(m in out for m in self._SIM_FAIL_MARKERS)

    def _on_sim_readyread(self):
        if self._sim_proc is not None:               # accumulate streamed output so the
            self._sim_output_buf += bytes(           # full log is available at finish
                self._sim_proc.readAll()).decode(errors="replace")

    def _on_sim_finished(self, code, _status):
        tail = bytes(self._sim_proc.readAll()).decode(errors="replace") if self._sim_proc else ""
        out = self._sim_output_buf + tail
        self._sim_last_output = out                  # keep for the no-result diagnostic
        tb = os.path.basename(self._sch_path)
        stem = os.path.splitext(tb)[0]

        if self._sim_simulator == "vacask":
            # xschem launches VACASK *detached* and returns in a fraction of a second, so
            # the result lands a moment later.  Poll for it, using the detached vacask
            # process (found in /proc) as the 'still running' signal: a long run is never
            # killed, and a failed run is caught as soon as vacask exits with no result.
            # xschem's own activity watchdog is moot now (it has already exited).
            if self._sim_watchdog is not None:
                self._sim_watchdog.stop()
                self._sim_watchdog = None
            self._sim_poll_stem = stem
            self._sim_poll_last = None
            self._sim_vacask_seen = False
            self._sim_vacask_gone_at = 0.0
            self._sim_poll_deadline = time.time() + 3600.0    # absolute backstop only
            self.top.run_sim.setText("Stop")
            self.top.set_sim_progress("running...")
            self._sim_timer = QtCore.QTimer(self)
            self._sim_timer.setInterval(300)
            self._sim_timer.timeout.connect(self._poll_sim_result)
            self._sim_timer.start()
            self._poll_sim_result()
            return

        # Ngspice: a non-zero exit (or a streamed error) is an immediate failure...
        if code != 0 or self._sim_reported_failure(out):
            self._reset_run_button()
            self.top.set_sim_status("failed!", False)
            head = (f"xschem exited with code {code}." if code != 0
                    else "The simulator reported an error and did not finish.")
            QtWidgets.QMessageBox.warning(
                self, "Run simulation", f"{head}\n\n{out[-1500:] or '(no output)'}")
            return
        # ...otherwise it may run detached and write its result a little later, so poll.
        self._sim_poll_stem = stem
        self._sim_poll_deadline = time.time() + 60.0
        self._sim_poll_last = None
        self.top.run_sim.setText("Stop")             # still cancellable while importing
        self.top.set_sim_progress("importing...")
        self._sim_timer = QtCore.QTimer(self)
        self._sim_timer.setInterval(300)
        self._sim_timer.timeout.connect(self._poll_sim_result)
        self._sim_timer.start()
        self._poll_sim_result()                      # also check immediately

    def _poll_sim_result(self):
        stem = self._sim_poll_stem
        result = self._find_sim_result(stem)
        if result is not None:
            try:
                size = os.path.getsize(result)
            except OSError:
                size = -1
            if size > 0 and self._sim_poll_last == (result, size):
                self._finish_sim_import(result)      # seen twice, size settled -> import
                return
            self._sim_poll_last = (result, size)     # let it settle for one more tick
            return
        now = time.time()
        if self._sim_simulator == "vacask":
            if self._fresh_abort_marker(stem):       # postprocess flagged an abort
                self._end_vacask_poll("aborted!", aborted=True)
            elif self._vacask_running():             # still simulating -> keep waiting
                self._sim_vacask_seen = True
                self._sim_vacask_gone_at = 0.0
            elif self._sim_vacask_seen:              # vacask finished, no result written
                if not self._sim_vacask_gone_at:
                    self._sim_vacask_gone_at = now   # brief grace for the file to land
                elif now - self._sim_vacask_gone_at > 1.5:
                    self._end_vacask_poll("failed!", aborted=False)
            elif now - self._sim_start > 12.0:       # vacask never even started
                self._end_vacask_poll("failed!", aborted=False)
            if now >= self._sim_poll_deadline:       # 1 h absolute backstop
                self._end_vacask_poll("failed!", aborted=False)
            return
        # Ngspice: deadline-based (it may run detached and write a little later)
        if now >= self._sim_poll_deadline:
            self._stop_sim_timer()
            self._reset_run_button()
            self.top.set_sim_status("failed!", False)
            log = (self._sim_last_output or "").strip()
            QtWidgets.QMessageBox.warning(
                self, "Run simulation",
                f"The simulation of {os.path.basename(self._sch_path)} FAILED: it "
                f"produced no result in\n{self._sim_output_dir()}\n\n"
                "The simulator most likely reported an error or the analysis was "
                "aborted - check its console / log for the cause.\n\n"
                "If you believe it actually succeeded, use 'Import simulation' to load "
                "the result file manually."
                + (f"\n\n--- simulator output ---\n{log[-1500:]}" if log else ""))

    def _end_vacask_poll(self, status, aborted):
        self._stop_sim_timer()
        self._reset_run_button()
        self.top.set_sim_status(status, False)
        log = self._read_vacask_log() or (self._sim_last_output or "").strip()
        what = ("aborted: the analysis ran but produced no result (e.g. a singular matrix)"
                if aborted else "failed: it produced no result")
        QtWidgets.QMessageBox.warning(
            self, "Run simulation",
            f"The VACASK simulation of {os.path.basename(self._sch_path)} {what}.\n"
            "See VACASK's console / log for the cause."
            + (f"\n\n--- simulator output ---\n{log[-1500:]}" if log else ""))

    @staticmethod
    def _vacask_pids():
        """PIDs of running VACASK processes.  xschem launches vacask detached (not in its
        process tree), so we scan /proc by command name."""
        pids = []
        if not os.path.isdir("/proc"):
            return pids
        for dd in os.listdir("/proc"):
            if not dd.isdigit():
                continue
            try:
                with open("/proc/" + dd + "/comm") as fh:
                    if "vacask" in fh.read():
                        pids.append(int(dd))
            except OSError:
                continue
        return pids

    def _vacask_running(self):
        # without /proc (e.g. Windows) we can't tell, so assume yes and let the deadline win
        return True if not os.path.isdir("/proc") else bool(self._vacask_pids())

    def _kill_vacask(self):
        """Terminate any detached VACASK process (xschem already exited, so it won't)."""
        import signal
        for pid in self._vacask_pids():
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

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
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.state.to_json())

    def on_load_design(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load conversion settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as fh:
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

    def closeEvent(self, event):
        """Stop any running simulation and its timers before the window closes, so a
        detached VACASK process or a polling timer cannot outlive the UI."""
        try:
            self._timer.stop()                            # the recompute debounce
            self._cancel_sim()                            # run/import timers + detached VACASK
        except Exception:                                 # noqa: BLE001
            pass
        super().closeEvent(event)

    # ---- the pipeline ----------------------------------------------------
    def recompute(self):
        self.design.set_file_info(io.info_for(self.net).summary)
        res = engine.convert(self.state, self.net)
        if res.mode == "structure":            # mirror the freq actually used (it may
            self.top.show_fext(res.metrics.get("f_extract"))   # have been auto-detected)
        self.design.update_results(res)
        self.plots.update_results(res)
