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


# VACASK is launched detached by xschem, which then quits (-q), so VACASK's console never
# reaches a terminal.  The run redirects it to this file inside the netlist dir; the GUI
# reads it back for "Show output" and for the failure / abort diagnostics.
VACASK_LOG = "vacask.log"


def vacask_log_path(sch_path: str) -> str:
    """Absolute path of the VACASK console log written for testbench `sch_path`."""
    cwd = os.path.dirname(os.path.abspath(sch_path))
    return os.path.join(cwd, "simulations", VACASK_LOG)


def simulate_command(sch_path: str, show_output: bool = True, simulator: str = "ngspice"):
    """Return (program, args, cwd) that netlists + simulates `sch_path` headlessly with
    the chosen `simulator` ("ngspice" or "vacask").

    Runs in the testbench's own directory, using its `xschemrc` (if present) and a
    `simulations/` directory for the netlist, then quits (-q).  Paths are wrapped in
    Tcl braces so spaces survive.  Either simulator's testbench writes its result to
    `sim_data/<tb>.txt` (ngspice via `wrdata`, VACASK via its `postprocess` script),
    so the GUI imports both the same way.

    ngspice: after `xschem netlist` (re)generates the SPICE netlist (a build artifact,
    not the `.sch`), its control block is patched *deterministically* for the mode, so
    the run never depends on a previous run's leftover edits:
      * show_output=False - `plot` lines commented out and a `quit` ensured -> ngspice
        runs quietly, writes its result and exits (the GUI auto-imports it).
      * show_output=True  - `plot` lines uncommented and any `quit` removed -> ngspice
        opens its plot windows / console and stays interactive.

    vacask: mirrors the testbench's VACASK launcher - select VACASK in the spectre
    category, set the Spectre netlist format, netlist and simulate.  (`show_output` is
    handled by the GUI via a SHOW_PLOTS env var the postprocess script honours.)
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
            # postprocess messages): xschem runs it detached and then quits, so without this
            # the output is lost.  Tcl exec `>&` redirects stdout+stderr; the run cd's into
            # the netlist dir, so a bare name lands there.
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

    # ngspice: SPICE netlist, deterministically patched per show_output
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
            # ngspice never drops to an interactive prompt (which would hang the run)
            "if {![regexp -line {^quit$} $d]} "
            "{regsub -line {^\\.endc} $d \"quit\\n.endc\" d}; ")
    tcl += ("set fp [open $nf w]; puts -nonewline $fp $d; close $fp}; "
            "xschem simulate")
    args += ["--command", tcl, tb]
    return "xschem", args, cwd
