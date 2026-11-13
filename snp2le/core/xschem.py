# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""xschem.py - integration with the Xschem schematic editor / simulator.

Pure Python (no Qt): detect whether `xschem` is installed and build the headless
command that netlists and simulates a testbench, mirroring the project's
`make sim-xschem` target:

    cd <testbench dir> && xschem -x -q --rcfile xschemrc --command '
        set netlist_dir <dir>/simulations; xschem save; xschem netlist; xschem simulate
    ' <testbench>.sch

The GUI runs the returned command with QProcess so it does not block the UI.
"""
from __future__ import annotations
import os
import posixpath
import re
import shutil
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def available() -> bool:
    """True if an `xschem` executable is on PATH and can be run.

    Checked once (cached).  We confirm with `xschem --version`; any clean
    execution counts (exit code varies across builds), only a missing or
    non-runnable binary counts as unavailable.
    """
    if shutil.which("xschem") is None:
        return False
    try:
        subprocess.run(["xschem", "--version"], capture_output=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


# xschem launches the simulator detached and then quits (-q), so the simulator's console
# never reaches a terminal.  Each run redirects it to a log inside the netlist dir, which the
# GUI and CLI read back for "Show output" and for the failure or abort diagnostics.
VACASK_LOG = "vacask.log"
NGSPICE_LOG = "ngspice.log"
XYCE_LOG = "xyce.log"
_SIM_LOG = {"vacask": VACASK_LOG, "ngspice": NGSPICE_LOG, "xyce": XYCE_LOG}

# the simulators the bundled testbenches are written for, in the GUI's dropdown order
SIMULATORS = ("ngspice", "vacask", "xyce")
NAMES = {"ngspice": "Ngspice", "vacask": "VACASK", "xyce": "Xyce"}
# xschem launches these two detached with their console redirected to a log, so a run is
# followed through the process and the log rather than through xschem
DETACHED = ("vacask", "xyce")


def simulator_for(sch_path: str) -> str:
    """The simulator a testbench is for, from its file name alone, so a folder named
    vacask_runs/ cannot pick VACASK for an Ngspice testbench.  Ngspice unless the name says
    otherwise."""
    name = os.path.basename(sch_path).lower()
    return next((s for s in ("vacask", "xyce") if s in name), "ngspice")


def sim_log_path(sch_path: str, simulator: str) -> str:
    """Absolute path of the console log captured for `simulator` running `sch_path`."""
    cwd = os.path.dirname(os.path.abspath(sch_path))
    return os.path.join(cwd, "simulations", _SIM_LOG.get(simulator, VACASK_LOG))


def vacask_log_path(sch_path: str) -> str:
    """Absolute path of the VACASK console log."""
    return sim_log_path(sch_path, "vacask")


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


# the line that names a testbench's result file, in the .sch or the generated netlist
_RESULT_TARGET = {"ngspice": re.compile(r"^\s*wrdata\s+(\S+)", re.M),
                  "xyce": re.compile(r"^\s*\.lin\b.*?\bfile\s*=\s*(\S+)", re.M | re.I)}


def sim_data_dir(sch_path: str, simulator: str = "ngspice") -> str:
    """Directory where `sch_path`'s testbench writes its simulation result.

    The location is the testbench's choice, not ours, so read it from the testbench
    itself instead of assuming a layout.  Ngspice: the `wrdata <target>` line in the
    .sch (or the generated netlist), resolved against the `simulations/` netlist dir
    the simulator runs in.  Xyce: the `FILE=` of the `.LIN` line, read the same way.
    VACASK: the `postprocess: wrote <file>` line of the
    captured console log - it appears once the run's postprocess has finished, so
    callers re-evaluate while polling; the folder is stable across runs.  Falls back
    to `plot_simulations/data/` next to the testbench (the bundled layout).
    """
    sch_path = os.path.abspath(sch_path)
    cwd = os.path.dirname(sch_path)
    netlist_dir = os.path.join(cwd, "simulations")
    if simulator == "vacask":
        hits = re.findall(r"postprocess:\s+wrote\s+(.+)",
                          _read_text(sim_log_path(sch_path, "vacask")))
        # the postprocess reports the result table first and then the figure PNG,
        # which lands in the sibling figures/ folder - only tables count here
        tables = [h.strip() for h in hits if os.path.splitext(h.strip())[1].lower()
                  in (".txt", ".csv", ".dat", ".data")]
        if tables:
            return os.path.dirname(tables[-1])
    else:
        target = _RESULT_TARGET.get(simulator, _RESULT_TARGET["ngspice"])
        stem = os.path.splitext(os.path.basename(sch_path))[0]
        for src in (sch_path, os.path.join(netlist_dir, stem + ".spice")):
            m = target.search(_read_text(src))
            if m:
                # a SPICE path: '/' separated on any platform, '\' is an escape there
                return os.path.normpath(
                    os.path.join(netlist_dir, posixpath.dirname(m.group(1))))
    return os.path.join(cwd, "plot_simulations", "data")


# extensions in a testbench's data folder that are never a result, and the ones of a table
_NON_DATA = (".raw", ".spice", ".inc", ".cir", ".net", ".log", ".out", ".svg", ".png",
             ".ps", ".pdf", ".sch", ".aborted")
_DATA_EXTS = (".txt", ".data", ".dat", ".csv")
_TOUCHSTONE = re.compile(r"\.s\d+p", re.I)


def find_result(data_dir: str, stem: str, since: float):
    """Newest result written in `data_dir` since `since` (epoch seconds), or None.  A file
    named after the testbench counts with any extension that is not a netlist, log or
    figure, since Ngspice `wrdata` targets vary and Xyce writes `.sNp`, and with 1 s of
    grace for a coarse file clock.  Without one, a table or Touchstone file counts only if
    it is strictly newer than `since`: with the grace, a run started right after another
    took the previous testbench's result for its own."""
    if not os.path.isdir(data_dir):
        return None
    named, data = [], []
    for f in os.listdir(data_dir):
        ext = os.path.splitext(f)[1].lower()
        if ext in _NON_DATA:
            continue
        p = os.path.join(data_dir, f)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if f.startswith(stem):
            if mt >= since - 1:                             # (re)written by this run
                named.append((mt, p))
        elif (ext in _DATA_EXTS or _TOUCHSTONE.fullmatch(ext)) and mt > since:
            data.append((mt, p))
    pool = named or data
    return max(pool)[1] if pool else None


def previous_results(data_dir: str, stem: str) -> list:
    """What an earlier run of testbench `stem` left in `data_dir`: its result table, its
    Touchstone file and the VACASK postprocess's abort marker.  A run deletes them first,
    so none can pass for its own result."""
    try:
        names = os.listdir(data_dir)
    except OSError:
        return []
    return [os.path.join(data_dir, f) for f in names
            if os.path.splitext(f)[0] == stem
            and (os.path.splitext(f)[1].lower() in (".txt", ".aborted")
                 or _TOUCHSTONE.fullmatch(os.path.splitext(f)[1]))]


def write_sim_range(cwd: str, f_min: float, f_max: float) -> None:
    """Write sim_range.inc (VACASK `var`), sim_range.spice (Ngspice `.csparam`) and
    sim_range.cir (Xyce `.param`) into
    `cwd`, so a testbench that includes them sweeps the band the model was fitted over (the
    loaded file's full span unless a fit range is set).  Both the GUI and the CLI call this
    before a run, so a run always matches the model it is simulating."""
    note = "auto-generated by snp2le from the fitted frequency band, overwritten on each run"
    with open(os.path.join(cwd, "sim_range.inc"), "w", newline="\n") as fh:   # VACASK / Spectre
        fh.write(f"// {note}\nvar f_min = {f_min:.6e}\nvar f_max = {f_max:.6e}\n")
    with open(os.path.join(cwd, "sim_range.spice"), "w", newline="\n") as fh:  # Ngspice (SPICE3)
        fh.write(f"* {note}\n.csparam f_min={f_min:.6e}\n.csparam f_max={f_max:.6e}\n")
    with open(os.path.join(cwd, "sim_range.cir"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(f"* {note}\n.param f_min={f_min:.6e}\n.param f_max={f_max:.6e}\n")  # Xyce


_SIM_PROC = {"vacask": "vacask", "ngspice": "ngspice", "xyce": "Xyce"}
_PROC = "/proc"


def simulator_pids(simulator: str) -> list:
    """PIDs of running processes of `simulator`.  xschem launches the simulator out of its
    own process tree and quits, so scan /proc by command name.  A zombie does not count: in
    a container whose PID 1 reaps no orphans, every finished run stays one, and the poll
    took that for a run still going until its deadline.  Empty where /proc is unavailable
    (e.g. Windows)."""
    name = _SIM_PROC.get(simulator, simulator)
    pids = []
    if not os.path.isdir(_PROC):
        return pids
    for d in os.listdir(_PROC):
        if not d.isdigit():
            continue
        try:
            with open(os.path.join(_PROC, d, "comm")) as fh:
                if name not in fh.read():
                    continue
            with open(os.path.join(_PROC, d, "stat")) as fh:
                stat = fh.read()
        except OSError:
            continue
        if stat[stat.rfind(")") + 2:][:1] not in ("Z", "X"):    # the state after "(comm) "
            pids.append(int(d))
    return pids


def simulator_running(simulator: str) -> bool:
    """True if a detached process for `simulator` is alive.  Returns False where /proc is
    unavailable (e.g. Windows), where the caller falls back to a wall-clock deadline."""
    return bool(simulator_pids(simulator))


def simulate_command(sch_path: str, show_output: bool = True, simulator: str = "ngspice"):
    """Return (program, args, cwd) that netlists + simulates `sch_path` headlessly with
    the chosen `simulator` ("ngspice", "vacask" or "xyce").

    Runs in the testbench's own directory, using its `xschemrc` (if present) and a
    `simulations/` directory for the netlist, then quits (-q).  Paths are wrapped in
    Tcl braces so spaces survive.  Either simulator's testbench writes its result to
    `plot_simulations/data/<tb>.txt` (Ngspice via `wrdata`, VACASK via its
    `postprocess` script), so the GUI imports both the same way.

    Ngspice: after `xschem netlist` (re)generates the SPICE netlist (a build artifact,
    not the `.sch`), its control block is patched *deterministically* for the mode, so
    the run never depends on a previous run's leftover edits:
      * show_output=False - `plot` lines commented out and a `quit` ensured -> Ngspice
        runs quietly, writes its result and exits (the GUI auto-imports it).
      * show_output=True  - `plot` lines uncommented and any `quit` removed -> Ngspice
        opens its plot windows / console and stays interactive.

    vacask: mirrors the testbench's VACASK launcher - select VACASK in the spectre
    category, set the Spectre netlist format, netlist and simulate.  (`show_output` is
    handled by the GUI via a SHOW_PLOTS env var the postprocess script honours.)

    xyce: Xschem's own "Xyce batch" entry, #3 in the spice category, on the SPICE netlist
    as it is, with the console captured to a log as for VACASK.  Xyce opens no window, so
    `show_output` changes nothing here, the GUI shows the log instead.
    """
    sch_path = os.path.abspath(sch_path)
    cwd = os.path.dirname(sch_path)
    tb = os.path.basename(sch_path)
    netlist_dir = os.path.join(cwd, "simulations")
    args = ["-x", "-q"]
    if os.path.exists(os.path.join(cwd, "xschemrc")):
        args += ["--rcfile", "xschemrc"]

    if simulator == "vacask":
        tcl = (
            f"set netlist_dir {{{netlist_dir}}}; "
            "set_sim_defaults; "                       # populate the sim() command table
            "set sim(spectre,default) 0; "             # #0 in the spectre category = VACASK
            # capture VACASK's console (banner, analysis progress, Completed/Failed/aborted,
            # postprocess messages). xschem runs it detached and then quits, so without this
            # the output is lost.  Tcl exec `>&` redirects stdout+stderr, and the run cd's
            # into the netlist dir, so a bare name lands there.
            f'set sim(spectre,0,cmd) {{vacask "$N" >& {VACASK_LOG}}}; '
            "xschem set netlist_type spectre; "        # generate a Spectre/VACASK netlist
            "write_data [save_params] "                # op-point .save file (as the launcher)
            "$netlist_dir/[file rootname [file tail [xschem get current_name]]].save; "
            "xschem save; xschem netlist; "
            # drop stale .raw output first: an aborted analysis (e.g. a singular matrix)
            # writes none, so without this the postprocess would re-read a previous run's
            # .raw and emit a result that imports as a false 'success'
            "foreach d [list $netlist_dir [file dirname $netlist_dir]] {"
            "foreach f [glob -nocomplain [file join $d *.raw]] {file delete -- $f}}; "
            "simulate")
        args += ["--command", tcl, tb]
        return "xschem", args, cwd

    if simulator == "xyce":
        tcl = (
            f"set netlist_dir {{{netlist_dir}}}; "
            "set_sim_defaults; "
            # set in full, so a simrc that numbers the spice simulators differently does
            # not hand the run to another one
            f'set sim(spice,3,cmd) {{Xyce "$N" >& {XYCE_LOG}}}; '
            "set sim(spice,3,fg) 0; set sim(spice,3,st) 1; "
            "set sim(spice,default) 3; "
            "xschem set netlist_type spice; "
            "xschem save; xschem netlist; simulate")
        args += ["--command", tcl, tb]
        return "xschem", args, cwd

    # Ngspice: SPICE netlist, deterministically patched per show_output.  (Ngspice suppresses
    # its console when stdout is not a TTY, so unlike VACASK there is no useful log to capture,
    # a failed run is caught from the missing result plus the process having exited.)
    nf = os.path.join(netlist_dir, os.path.splitext(tb)[0] + ".spice")
    tcl = (f"set netlist_dir {{{netlist_dir}}}; xschem save; xschem netlist; "
           f"set nf {{{nf}}}; "
           "if {[file exists $nf]} {"
           "set fp [open $nf r]; set d [read $fp]; close $fp; ")
    if show_output:
        tcl += (
            "regsub -all -line {^\\*plot } $d {plot } d; "      # show plot windows
            "regsub -all -line {^quit$} $d {*quit} d; ")        # stay interactive
    else:
        tcl += (
            "regsub -all -line {^plot } $d {*plot } d; "        # silence plot windows
            "regsub -all -line {^\\*quit} $d {quit} d; "        # activate a commented quit
            # ...and if the control block still has no exit, add one before .endc so
            # Ngspice never drops to an interactive prompt (which would hang the run)
            "if {![regexp -line {^quit$} $d]} "
            "{regsub -line {^\\.endc} $d \"quit\\n.endc\" d}; ")
    tcl += ("set fp [open $nf w]; puts -nonewline $fp $d; close $fp}; "
            "xschem simulate")
    args += ["--command", tcl, tb]
    return "xschem", args, cwd
