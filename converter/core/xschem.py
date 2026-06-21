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


def simulate_command(sch_path: str, show_output: bool = True):
    """Return (program, args, cwd) that netlists + simulates `sch_path` headlessly.

    Runs in the testbench's own directory, using its `xschemrc` (if present) and a
    `simulations/` netlist directory, then quits (-q).  The netlist dir is wrapped
    in Tcl braces so paths with spaces survive.

    When `show_output` is False the freshly generated netlist (a build artifact, not
    the testbench `.sch`) is patched in place before simulating: the `plot` lines are
    commented out and the trailing `quit` is uncommented, so ngspice runs the control
    block (still writing its result) without opening its console or plot windows.
    """
    sch_path = os.path.abspath(sch_path)
    cwd = os.path.dirname(sch_path)
    tb = os.path.basename(sch_path)
    netlist_dir = os.path.join(cwd, "simulations")
    tcl = f"set netlist_dir {{{netlist_dir}}}; xschem save; xschem netlist; "
    if not show_output:
        nf = os.path.join(netlist_dir, os.path.splitext(tb)[0] + ".spice")
        tcl += (
            f"set nf {{{nf}}}; "
            "if {[file exists $nf]} {"
            "set fp [open $nf r]; set d [read $fp]; close $fp; "
            "regsub -all -line {^plot } $d {*plot } d; "        # silence plot windows
            "regsub -all -line {^\\*quit} $d {quit} d; "        # activate a commented quit
            # ...and if the control block still has no exit, add one before .endc so
            # ngspice never drops to an interactive prompt (which would hang the run)
            "if {![regexp -line {^quit$} $d]} "
            "{regsub -line {^\\.endc} $d \"quit\\n.endc\" d}; "
            "set fp [open $nf w]; puts -nonewline $fp $d; close $fp}; ")
    tcl += "xschem simulate"
    args = ["-x", "-q"]
    if os.path.exists(os.path.join(cwd, "xschemrc")):
        args += ["--rcfile", "xschemrc"]
    args += ["--command", tcl, tb]
    return "xschem", args, cwd
