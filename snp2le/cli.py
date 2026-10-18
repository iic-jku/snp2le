#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""cli.py - command-line interface for batch and scripted use.

    # universal macromodel to an Ngspice netlist
    snp2le -b convert coupler.s4p --mode universal --order 12 -o coupler.spice

    # structure extraction at 7 GHz, both dialects, print values and tolerances
    snp2le -b convert ind.s2p --mode structure --structure inductor-pi \\
        --fext 7GHz --format both --values --tolerances

    # wideband inductor model, fitted over the whole band (no f_ext)
    snp2le -b convert ind.s2p --mode structure --structure inductor-wideband --values

    # center-tapped inductor from measured data, Q emphasised around its peak
    snp2le -b convert ct.s3p --mode structure --structure inductor-ct \\
        --shunt-accuracy --peak-q-weight 3 --ct-port 1

    # fit only the 110 to 170 GHz sub-band of a wider EM sweep
    snp2le -b convert core.s7p --mode universal --order 24 --fmin 110GHz --fmax 170GHz

    # enforce passivity only down to 1.05, keeping accuracy strict enforcement would cost
    snp2le -b convert bpf.s2p --mode universal --order 13 --passivity-ceiling 1.05

    # add the passive's thermal noise, kT(I - S S^H) at the ports, to the macromodel
    snp2le -b convert wpd.s3p --mode universal --order 13 --thermal-noise --format both

    # a file with a 0 Hz sample is pinned to it by default, so a coil keeps its DC resistance.
    # Here the DC modes without a path to ground also get 1 uS, for harmonic balance
    snp2le -b convert coil.s2p --mode universal --order 13 --dc-island-leak 1e-6

    # convert, run an Xschem testbench, and show data-vs-model-vs-sim plots
    snp2le -b convert bpf.s2p --mode universal --order 13 \\
        -o netlist/spice/two_port.spice \\
        --simulate testbenches/xschem/two_port_tb_acsp_ngspice.sch --plot

Globs are expanded.  With --format both, two files are written per input.  The exit code is
non-zero if any conversion or a requested simulation fails.  A failed conversion writes
nothing and removes the files an earlier run left at its output paths.
"""
from __future__ import annotations
import argparse
import glob
import os
import re
import shutil
import sys
import time

from snp2le.core import io, engine, units, netlist, universal
from snp2le.core.progress import format_duration
from snp2le.core.state import ConverterState
from snp2le.core.structures import (STRUCTURES, get_structure, inductor_fit,
                                    structure_items)

# extensions in the testbench's data folder that are never a result table
_NON_DATA = {".raw", ".spice", ".inc", ".cir", ".net", ".log", ".out", ".svg", ".png",
             ".ps", ".pdf", ".sch", ".aborted"}
_DATA_EXTS = {".txt", ".data", ".dat", ".csv"}


class _ProgressLine:
    """A one-line progress bar redrawn in place on stderr.

    Only used on a terminal.  Piped or redirected output gets the ordinary
    status lines and nothing else, so logs, CI transcripts and `snp2le ... >
    file` stay diffable instead of filling with carriage returns.  It writes to
    stderr so a piped stdout keeps carrying only the [ OK ] lines.
    """

    _WIDTH = 22                      # characters of bar, excluding the brackets
    _MIN_INTERVAL = 0.1              # s between redraws, ~10 Hz is smooth enough

    def __init__(self, label, stream=None):
        self._label = label
        # Bind the stream now, not per write.  fit_universal redirects sys.stderr
        # for the whole fit to swallow scikit-rf's chatter, so a late lookup would
        # send the bar into that StringIO during the one phase worth watching.
        self._stream = stream or sys.stderr
        self._t0 = time.monotonic()
        self._last = 0.0
        self._width = 0              # characters written by the last redraw

    def __call__(self, fraction, message=""):
        now = time.monotonic()
        if now - self._last < self._MIN_INTERVAL and fraction < 1.0:
            return
        self._last = now
        filled = int(round(self._WIDTH * max(0.0, min(1.0, fraction))))
        bar = "#" * filled + "-" * (self._WIDTH - filled)
        line = (f"  {self._label} [{bar}] {fraction * 100:3.0f}%  "
                f"{format_duration(now - self._t0)}  {message}")
        self._write(line[:max(20, shutil.get_terminal_size((80, 24)).columns - 1)])

    def close(self):
        """Erase the line so the next print starts on a clean row."""
        if self._width:
            self._stream.write("\r" + " " * self._width + "\r")
            self._stream.flush()
        self._width = 0

    def _write(self, line):
        pad = max(0, self._width - len(line))
        self._stream.write("\r" + line + " " * pad)
        self._stream.flush()
        self._width = len(line)


def _progress_for(args, label):
    """A `_ProgressLine` for this run, or None when progress is not wanted.

    `--progress` / `--no-progress` decide it outright; unset means show it on a
    terminal only.  `--quiet` silences it like every other status output.
    """
    if args.quiet or args.progress is False:
        return None
    if args.progress is None and not sys.stderr.isatty():
        return None
    return _ProgressLine(label)


def _freq(text):
    """argparse type for a frequency, with a readable error."""
    try:
        return units.parse_eng(text)
    except Exception:                                        # noqa: BLE001
        raise argparse.ArgumentTypeError(f"invalid frequency '{text}' (e.g. 7GHz, 2.4e9)")


def _stages(text):
    """argparse type for the RLGC ladder stage count (an integer from 1 to 10)."""
    try:
        n = int(text)
    except Exception:                                       # noqa: BLE001
        raise argparse.ArgumentTypeError(f"invalid stage count '{text}' (an integer 1..10)")
    if not 1 <= n <= 10:
        raise argparse.ArgumentTypeError(f"--stages must be between 1 and 10 (got {n})")
    return n


def _coil_segments(text):
    """argparse type for the wideband inductors' fixed coil segment count."""
    lo, hi = inductor_fit.SEGMENT_RANGE
    try:
        n = int(text)
    except Exception:                                       # noqa: BLE001
        raise argparse.ArgumentTypeError(f"invalid segment count '{text}' (an integer "
                                         f"{lo}..{hi})")
    if not lo <= n <= hi:
        raise argparse.ArgumentTypeError(f"--segments must be between {lo} and {hi} (got {n})")
    return n


def _positive(text):
    """argparse type for a positive number (the wideband fit weights)."""
    try:
        v = float(text)
    except Exception:                                       # noqa: BLE001
        # the value is optional, so an input file right after the option lands here
        raise argparse.ArgumentTypeError(f"invalid number '{text}' (an option without a "
                                         f"value goes after the input files)")
    if not (v > 0 and v != float("inf")):
        raise argparse.ArgumentTypeError(f"must be a positive number (got {text})")
    return v


def _order(text):
    """argparse type for --order (an integer, 2 or more, the smallest model order)."""
    try:
        n = int(text)
    except Exception:                                       # noqa: BLE001
        raise argparse.ArgumentTypeError(f"invalid order '{text}' (an integer, 2 or more)")
    if n < 2:
        raise argparse.ArgumentTypeError(f"--order must be 2 or more (got {n})")
    return n


def _band_edge(text):
    """argparse type for --fmin (a frequency, 0 Hz or more)."""
    v = _freq(text)
    if not v >= 0:
        raise argparse.ArgumentTypeError(f"a fit range edge must be 0 Hz or more (got {text})")
    return v


def _band_top(text):
    """argparse type for --fmax (above 0 Hz, since the fit treats 0 as an open edge)."""
    v = _freq(text)
    if not v > 0:
        raise argparse.ArgumentTypeError(f"--fmax must be above 0 Hz (got {text})")
    return v


def _seconds(text):
    """argparse type for --timeout (seconds, above 0)."""
    try:
        v = float(text)
    except Exception:                                       # noqa: BLE001
        raise argparse.ArgumentTypeError(f"invalid time '{text}' (seconds, e.g. 300)")
    if not 0 < v < float("inf"):
        raise argparse.ArgumentTypeError(f"--timeout must be above 0 s (got {text})")
    return v


def _simulator_for(sch):
    """The simulator a testbench is for, from its file name alone as the GUI does, so a folder
    named vacask_runs/ cannot pick VACASK for an Ngspice testbench."""
    return "vacask" if "vacask" in os.path.basename(sch).lower() else "ngspice"


def _corner(text):
    """argparse type for the DC pin's corner frequency (above 0 Hz)."""
    v = _freq(text)
    if not v > 0:
        raise argparse.ArgumentTypeError(f"--dc-pin-fc must be above 0 Hz (got {text})")
    return v


def _leak(text):
    """argparse type for the DC pin's island leak (0 S or more)."""
    try:
        v = float(text)
    except Exception:                                       # noqa: BLE001
        raise argparse.ArgumentTypeError(f"invalid conductance '{text}' (e.g. 1e-6)")
    if not 0 <= v < float("inf"):
        raise argparse.ArgumentTypeError(f"--dc-island-leak must be 0 S or more (got {text})")
    return v


def _wideband_options_given(args):
    """The wideband fit options set on the command line, by their option names."""
    return [name for name, on in (("--basic", args.basic), ("--segments", args.segments),
                                  ("--substrate", args.substrate != "auto"),
                                  ("--peak-q-weight", args.peak_q_weight),
                                  ("--shunt-accuracy", args.shunt_accuracy),
                                  ("--ct-port", args.ct_port)) if on]


def _passivity_ceiling(text):
    """argparse type for the passivity ceiling (a float from 1.0 to 1.2)."""
    try:
        v = float(text)
    except Exception:                                       # noqa: BLE001
        raise argparse.ArgumentTypeError(
            f"invalid passivity ceiling '{text}' (a number, e.g. 1.05)")
    if not universal.PASSIVITY_CEILING_MIN <= v <= universal.PASSIVITY_CEILING_MAX:
        raise argparse.ArgumentTypeError(
            f"--passivity-ceiling must be between {universal.PASSIVITY_CEILING_MIN:.1f} and "
            f"{universal.PASSIVITY_CEILING_MAX:.1f} (got {v})")
    return v


def _out_path(src, explicit, dialect, n_inputs, n_formats):
    ext = "inc" if dialect == "vacask" else "spice"          # VACASK writes .inc
    if explicit and n_inputs == 1:
        if n_formats == 1:
            return explicit
        return f"{os.path.splitext(explicit)[0]}.{ext}"      # both: keep -o dir + stem
    base = os.path.splitext(os.path.basename(src))[0]         # many inputs: after each source
    return f"{base}.{ext}"


def _remove_stale(outs, written):
    """Delete what an earlier run left at the paths a failed conversion would have written.
    A file there would pass for this run's result, for example an old noiseless netlist after
    a refused --thermal-noise, which a Makefile then takes as up to date.  Files this run
    wrote stay (two inputs can share an output name)."""
    for out in outs:
        if os.path.abspath(out) in written or not os.path.isfile(out):
            continue
        try:
            os.remove(out)
            print(f"       removed {out}, left there by an earlier run", file=sys.stderr)
        except OSError as exc:
            print(f"[WARN] could not remove {out} left there by an earlier run: {exc}",
                  file=sys.stderr)


def _valid_sparams(names, n):
    """Keep only S-parameter selectors valid for an n-port, warning about the rest."""
    out = []
    for name in names:
        m = re.fullmatch(r"[sS]([1-9])([1-9])", name)
        if m and int(m.group(1)) <= n and int(m.group(2)) <= n:
            out.append(f"S{m.group(1)}{m.group(2)}")
        else:
            print(f"[WARN] ignoring plot selector '{name}' (not an S-parameter of a "
                  f"{n}-port)", file=sys.stderr)
    return out


def _print_values(res):
    if not res.value_rows:
        return
    print("       element values:")
    for lab, val, unit in res.value_rows:
        s = units.format_eng(val, unit) if unit else f"{val:.4g}"
        print(f"         {lab:8s} = {s}")


def _print_tolerances(res):
    if not res.value_drift:
        print("       tolerances: none, this model has no per-element tolerance")
        return
    print("       tolerances (|data-model|/model at f_ext):")
    for lab, pct in res.value_drift.items():
        print(f"         {lab:8s} = {pct:.1f}%")


def _default_sparams(n):
    if n == 2:
        return ["S11", "S21", "S12", "S22"]
    return (["S11"] + [f"S{i}1" for i in range(2, n + 1)])[:4]   # match plus couplings


def _tail_log(path, header):
    """Print the tail of a simulator log file (VACASK's captured console) to stderr."""
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, errors="replace") as fh:
            txt = fh.read().strip()
    except OSError:
        return
    if txt:
        print(f"  --- {header} ---", file=sys.stderr)
        print("  " + txt[-1500:].replace("\n", "\n  "), file=sys.stderr)


def _find_result(sim_data, stem, start):
    """Newest result file freshly written by this run: prefer one named after the testbench,
    else any data-style file (Ngspice wrdata targets vary)."""
    if not os.path.isdir(sim_data):
        return None
    named, data = [], []
    for f in os.listdir(sim_data):
        ext = os.path.splitext(f)[1].lower()
        if ext in _NON_DATA:
            continue
        p = os.path.join(sim_data, f)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt < start - 1:                                   # not (re)written this run
            continue
        (named if f.startswith(stem) else data).append((mt, p))
    pool = named or [x for x in data if os.path.splitext(x[1])[1].lower() in _DATA_EXTS]
    return max(pool)[1] if pool else None


def _run_testbench(sch, simulator, show_output, sweep, timeout):
    """Run an Xschem testbench with `simulator` and return the imported result path, or None.

    `sweep` is the (f_min, f_max) the exported model was fitted over, which is what the
    testbench sweeps.  Both Ngspice and VACASK are launched detached by xschem (which
    returns at once with an empty console), so the outcome is read the same way for both:
    sync the sweep to the fitted band, then poll for the result while the simulator process
    is alive.  When the process has exited with no result the run failed, and VACASK's
    captured log and .aborted marker give the specific cause."""
    import subprocess
    import time
    from snp2le.core import xschem
    if not xschem.available():
        print("xschem not found on PATH, cannot run a testbench", file=sys.stderr)
        return None
    sch = os.path.abspath(sch)
    if not os.path.isfile(sch):
        print(f"testbench not found: {sch}", file=sys.stderr)
        return None

    prog, args, cwd = xschem.simulate_command(sch, show_output=show_output, simulator=simulator)
    os.makedirs(os.path.join(cwd, "simulations"), exist_ok=True)
    if sweep is not None:                                    # the sweep follows the fit
        try:
            xschem.write_sim_range(cwd, float(sweep[0]), float(sweep[1]))
        except (TypeError, IndexError, ValueError, OSError) as exc:
            print(f"[WARN] could not sync the testbench sweep to the fitted band "
                  f"(the last-written sim_range is used instead): {exc}", file=sys.stderr)

    # Where the testbench writes its result: read from the testbench itself (Ngspice
    # wrdata / VACASK log), falling back to the bundled layout.  Re-evaluated while
    # polling below, since the VACASK log only reveals the folder once a run finishes.
    def sim_data_dir():
        return xschem.sim_data_dir(sch, simulator)

    stem = os.path.splitext(os.path.basename(sch))[0]
    log = xschem.sim_log_path(sch, simulator) if simulator == "vacask" else None
    for stale in (os.path.join(sim_data_dir(), stem + ".txt"),      # a clean run this time
                  os.path.join(sim_data_dir(), stem + ".aborted")):
        try:
            os.remove(stale)
        except OSError:
            pass
    if simulator == "ngspice":                  # wrdata cannot create its target folder
        os.makedirs(sim_data_dir(), exist_ok=True)

    env = os.environ.copy()
    if simulator == "vacask" and show_output:               # let the postprocess pop its plot
        env["SHOW_PLOTS"] = "1"
    print(f"  running {os.path.basename(sch)} with {simulator}...")
    start = time.time()
    try:
        subprocess.run([prog, *args], cwd=cwd, env=env,
                       capture_output=not show_output, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"  xschem did not return within {timeout:.0f} s", file=sys.stderr)
        return None

    settle = [None]

    def settled():                                          # appeared and stopped growing
        r = _find_result(sim_data_dir(), stem, start)
        if r is None:
            return None
        try:
            size = os.path.getsize(r)
        except OSError:
            return None
        if size > 0 and settle[0] == (r, size):
            return r
        settle[0] = (r, size)
        return None

    def aborted():
        try:
            return os.path.getmtime(
                os.path.join(sim_data_dir(), stem + ".aborted")) >= start - 1
        except OSError:
            return False

    def fail(msg):
        print("  " + msg, file=sys.stderr)
        _tail_log(log, "VACASK console")
        if simulator != "vacask":
            print("  Ngspice keeps no log here. Run the testbench directly or open it in "
                  "xschem to see the error", file=sys.stderr)
        return None

    seen, gone_at, deadline = False, 0.0, start + timeout
    while time.time() < deadline:
        r = settled()
        if r is not None:
            if show_output and log:
                _tail_log(log, "VACASK console")
            return r
        if simulator == "vacask" and aborted():
            return fail("the analysis aborted (e.g. a singular matrix), no result written")
        if xschem.simulator_running(simulator):
            seen, gone_at = True, 0.0
        elif seen:                                          # ran, then exited with no result
            gone_at = gone_at or time.time()
            if time.time() - gone_at > 1.5:
                return fail(f"{simulator} finished without writing a result")
        elif os.path.isdir("/proc") and time.time() - start > 12.0:
            # never even started / instant fail - only detectable where /proc exists;
            # without it (e.g. Windows) the --timeout deadline above rules
            return fail(f"{simulator} produced no result (check the testbench and models)")
        time.sleep(0.3)
    return fail(f"no result for '{stem}' after {timeout:.0f} s")


def _show_plots(res, sim, sparams):
    import numpy as np
    import matplotlib
    if matplotlib.get_backend().lower().endswith("agg"):     # no interactive display
        raise RuntimeError("no display available (matplotlib backend is non-interactive)")
    import matplotlib.pyplot as plt
    f = np.asarray(res.freq, float) / 1e9
    data = np.asarray(res.data_s)
    model = np.asarray(res.model_s)
    n = len(sparams)
    fig, ax = plt.subplots(2, n, figsize=(3.6 * n, 6.0), squeeze=False)
    for c, name in enumerate(sparams):
        i, j = int(name[1]) - 1, int(name[2]) - 1
        d, m = data[:, i, j], model[:, i, j]
        a0, a1 = ax[0][c], ax[1][c]
        a0.plot(f, 20 * np.log10(np.abs(d) + 1e-12), color="0.5", lw=1.4, label="data")
        a0.plot(f, 20 * np.log10(np.abs(m) + 1e-12), "b--", lw=1.6, label="model")
        a1.plot(f, np.unwrap(np.angle(d)) * 180 / np.pi, color="0.5", lw=1.4)
        a1.plot(f, np.unwrap(np.angle(m)) * 180 / np.pi, "b--", lw=1.6)
        if sim and name in sim:
            sf = np.asarray(sim["f"], float) / 1e9
            if sim[name].get("db") is not None:
                a0.plot(sf, sim[name]["db"], "r-.", lw=1.8, label="sim")
            if sim[name].get("deg") is not None:
                ph = np.unwrap(np.deg2rad(np.asarray(sim[name]["deg"], float))) * 180 / np.pi
                a1.plot(sf, ph, "r-.", lw=1.8)
        a0.set_title(name)
        a0.set_ylabel("|S| (dB)")
        a0.grid(alpha=.3)
        a1.set_ylabel("phase (deg)")
        a1.set_xlabel("f (GHz)")
        a1.grid(alpha=.3)
        if c == 0:
            a0.legend(fontsize=8)
    fig.tight_layout()
    plt.show()


def cmd_convert(args):
    # None means not given, so a --structure that universal mode ignores can be named.  The
    # default stays out of args, so a caller can run the same Namespace twice.
    key = "inductor-pi" if args.structure is None else args.structure
    if args.mode == "structure":
        valid = {k for k, _, _ in structure_items()}
        if key not in valid:
            print(f"unknown structure '{key}'. Valid keys: "
                  f"{', '.join(sorted(valid))}", file=sys.stderr)
            return 2

    paths, missing = [], []
    for pat in args.inputs:
        hits = sorted(glob.glob(pat))
        if not hits and not os.path.exists(pat):
            print(f"[FAIL] no file matches '{pat}'", file=sys.stderr)
            missing.append(pat)
            continue
        paths.extend(hits or [pat])
    if not paths:
        if not missing:
            print("no input files", file=sys.stderr)
        return 1 if missing else 2
    if args.output and len(paths) > 1:
        print("[WARN] -o is ignored with multiple inputs, each output is named after its "
              "source", file=sys.stderr)
    elif args.output and (os.path.isdir(args.output)
                          or args.output.endswith(("/", os.sep))):
        # with --format both the stem would be the folder's name, or empty after a separator
        print(f"[FAIL] -o {args.output}: that is a folder, -o takes a file name",
              file=sys.stderr)
        return 1

    # the ceiling is what the enforcement aims at, so it means nothing without it
    if args.passivity_ceiling is not None and not args.passive:
        print("[WARN] --passivity-ceiling is ignored with --no-passive, which exports the "
              "raw fit untouched", file=sys.stderr)
    p_ceiling = (universal.PASSIVITY_CEILING_DEFAULT if args.passivity_ceiling is None
                else args.passivity_ceiling)
    given = _wideband_options_given(args)
    struct = get_structure(key) if args.mode == "structure" else None
    named_wideband = getattr(STRUCTURES.get(key), "wideband", False)
    if given and not (struct is not None and struct.wideband):
        one = len(given) == 1
        why = (f"{'it needs' if one else 'these need'} --mode structure" if named_wideband
               else f"{'it applies' if one else 'these apply'} to the wideband inductor "
                    f"structures (inductor-wideband, inductor-ct) only")
        print(f"[WARN] {', '.join(given)} ignored, {why}", file=sys.stderr)
    elif given:
        if args.ct_port is not None and struct.n_ports != 3:
            print("[WARN] --ct-port is ignored, it applies to inductor-ct only",
                  file=sys.stderr)
        try:                                  # the fit's own rules, before any file is read
            inductor_fit.check_options(
                struct.n_ports, basic=args.basic, segments=args.segments,
                substrate=args.substrate, peak_q_weight=args.peak_q_weight,
                shunt_accuracy=args.shunt_accuracy,
                center_tap=args.ct_port if struct.n_ports == 3 else None)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    if struct is not None and struct.wideband:
        unused = [name for name, on in (("--fext", args.fext is not None),
                                        ("--tolerances", args.tolerances)) if on]
        if unused:
            print(f"[WARN] {', '.join(unused)} ignored, the wideband inductors are fitted "
                  f"over the band and have no extraction frequency", file=sys.stderr)
    if args.mode != "structure":
        unused = [name for name, on in (("--structure", args.structure is not None),
                                        ("--fext", args.fext is not None),
                                        ("--stages", args.stages is not None),
                                        ("--no-iso-r", not args.iso_r),
                                        ("--tolerances", args.tolerances)) if on]
        if unused:
            print(f"[WARN] {', '.join(unused)} ignored in universal mode, "
                  f"{'it applies' if len(unused) == 1 else 'these apply'} to structure "
                  f"models", file=sys.stderr)
    elif struct is not None:
        unused = [name for name, on in (
            ("--stages", args.stages is not None and key != "tline-rlgc"),
            ("--no-iso-r", not args.iso_r and key not in ("wilkinson-inphase", "branchline"))
        ) if on]
        if unused:
            print(f"[WARN] {', '.join(unused)} ignored, {key} has no such option",
                  file=sys.stderr)
    if args.thermal_noise and args.mode == "structure":
        print("[WARN] --thermal-noise is ignored in structure mode, whose resistors are the "
              "structure's loss and always carry their thermal noise", file=sys.stderr)
    pin_given = [name for name, on in (("--dc-pin", args.dc_pin is True),
                                       ("--dc-pin-fc", args.dc_pin_fc is not None),
                                       ("--dc-island-leak", args.dc_island_leak is not None))
                 if on]
    if pin_given and args.mode == "structure":
        print(f"[WARN] {', '.join(pin_given)} ignored in structure mode, whose extraction "
              f"drops the 0 Hz point", file=sys.stderr)
    elif pin_given and args.dc_pin is False:
        print(f"[WARN] {', '.join(pin_given)} ignored with --no-dc-pin", file=sys.stderr)

    formats = ["ngspice", "vacask"] if args.format == "both" else [args.format]
    rc = 1 if missing else 0
    last_res = None
    written = set()                     # absolute paths this run wrote
    # warn about a renamed .SUBCKT only for a name given with -o, not one taken from the source
    named = bool(args.output) and len(paths) == 1
    for src in paths:
        outs = [_out_path(src, args.output, d, len(paths), len(formats)) for d in formats]
        try:
            net = io.load_touchstone(src)
        except Exception as exc:                          # noqa: BLE001
            print(f"[FAIL] {src}: {exc}", file=sys.stderr)
            _remove_stale(outs, written)
            rc = 1
            continue
        state = ConverterState(
            mode=args.mode, structure_key=key,
            max_order=args.order, enforce_passivity=args.passive,
            passivity_ceiling=p_ceiling, thermal_noise=args.thermal_noise,
            dc_pin=args.dc_pin is not False,
            dc_pin_fc=ConverterState.dc_pin_fc if args.dc_pin_fc is None else args.dc_pin_fc,
            dc_island_leak=(ConverterState.dc_island_leak if args.dc_island_leak is None
                            else args.dc_island_leak),
            f_extract=ConverterState.f_extract if args.fext is None else args.fext,
            n_segments=2 if args.stages is None else args.stages, iso_resistor=args.iso_r,
            basic_model=args.basic, coil_segments=args.segments or 0,
            substrate=args.substrate, peak_q_weight=args.peak_q_weight or 0.0,
            shunt_accuracy=args.shunt_accuracy or 0.0, center_tap=args.ct_port or 0,
            f_min=args.fmin, f_max=args.fmax)
        bar = _progress_for(args, os.path.basename(src))
        t_start = time.monotonic()
        crash = None
        try:
            res = engine.convert(state, net, progress=bar)
        except Exception as exc:                          # noqa: BLE001
            # one file that breaks the engine must not end the batch for the files after it
            crash = engine.error_text(exc)
        finally:
            if bar is not None:
                bar.close()
        if crash is not None:                             # after the bar has cleared its line
            print(f"[FAIL] {src}: {crash}", file=sys.stderr)
            _remove_stale(outs, written)
            rc = 1
            continue
        elapsed = time.monotonic() - t_start
        if not res.ok:
            print(f"[FAIL] {src}: {res.error}", file=sys.stderr)
            _remove_stale(outs, written)
            rc = 1
            continue
        if res.noise is not None and not res.noise.ok:
            # a noiseless netlist under a name the caller expects to be noisy would go
            # into a noise budget unnoticed, so nothing is written
            print(f"[FAIL] {src}: {res.noise.message}", file=sys.stderr)
            _remove_stale(outs, written)
            rc = 1
            continue
        last_res = res
        for dialect, out in zip(formats, outs):
            if res.ir is not None:
                # name the .SUBCKT after the output file (bpf_le.spice -> bpf_le), so a
                # testbench that instantiates that name resolves the .include.  The GUI export
                # does the same.  The default 's_equivalent' would not match the testbench.
                stem = os.path.splitext(os.path.basename(out))[0]
                res.ir.name = netlist.safe_subckt_name(stem)
                if res.ir.name != stem and named:
                    print(f"[WARN] {out}: the subcircuit is named {res.ir.name}, since "
                          f"'{stem}' is not a valid name in both Ngspice and VACASK. Name "
                          f"the file {res.ir.name}{os.path.splitext(out)[1]} to keep the "
                          f"two equal", file=sys.stderr)
                text = (netlist.render_vacask(res.ir) if dialect == "vacask"
                        else netlist.render_ngspice(res.ir))
            else:
                text = res.vacask if dialect == "vacask" else res.ngspice
            if os.path.isdir(out):
                print(f"[FAIL] {src} -> {out}: that is a folder, -o takes a file name",
                      file=sys.stderr)
                rc = 1
                continue
            try:
                parent = os.path.dirname(os.path.abspath(out))
                os.makedirs(parent, exist_ok=True)
                with open(out, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                written.add(os.path.abspath(out))
            except OSError as exc:
                print(f"[FAIL] {src} -> {out}: {exc}", file=sys.stderr)
                rc = 1
                continue
            if not args.quiet:
                if res.mode == "universal":
                    dc = ("" if res.dc is None
                          else "  dc=solvable" if res.dc.ok else "  dc=SINGULAR")
                    sig = ("" if res.sigma_max != res.sigma_max
                           else f"  sigma_max={res.sigma_max:.3f}")
                    noise = "  noise=thermal" if res.noise is not None else ""
                    pin = "  dc_pinned" if res.dc_pin is not None and res.dc_pin.ok else ""
                    extra = (f"rms={res.rms_error:.2e}  order={res.model_order}"
                             f" ({res.n_poles} poles){sig}{dc}{noise}{pin}")
                elif res.metrics.get("f_fit_max") is not None:   # wideband, no f_ext
                    n = res.metrics.get("segments", 1)
                    extra = (f"fit to {units.format_eng(res.metrics['f_fit_max'], 'Hz')}, "
                             f"{n} segment{'' if n == 1 else 's'}"
                             f"{' per half' if res.n_ports == 3 else ''}")
                else:
                    extra = f"f_ext={units.format_eng(res.metrics.get('f_extract'), 'Hz')}"
                print(f"[ OK ] {src} -> {out}  ({dialect}, {extra}, "
                      f"{format_duration(elapsed)})")
        # a singular DC operating point makes the netlist unsimulable, so always warn
        if res.dc is not None and not res.dc.ok:
            print(f"[WARN] {src}: DC operating point may be singular "
                  f"(margin {res.dc.margin:.0e}), try a lower --order or --passive",
                  file=sys.stderr)
        if (pin_given and args.dc_pin is not False and res.mode == "universal"
                and res.dc_pin is None):
            print(f"[WARN] {src}: {', '.join(pin_given)} ignored, the file has no finite 0 Hz "
                  f"sample", file=sys.stderr)
        if not args.quiet:
            for m in res.messages:
                print(f"       note: {m}")
        show_tolerances = args.tolerances and struct is not None and not struct.wideband
        if (args.quiet and len(paths) > 1
                and ((args.values and res.value_rows) or show_tolerances)):
            print(f"{src}:")                 # --quiet drops the status line that names it
        if args.values:
            _print_values(res)
        if show_tolerances:                  # else a warning said it is ignored
            _print_tolerances(res)

    # optional: run a testbench, then show the data-vs-model-vs-sim plots
    sim = None
    if args.simulate and last_res is None:
        print("[WARN] no successful conversion, skipping --simulate", file=sys.stderr)
    elif args.simulate:
        if len(paths) > 1:
            print("[WARN] --simulate uses the last converted file, and the testbench's DUT "
                  "must match it", file=sys.stderr)
        simr = args.simulator or _simulator_for(args.simulate)
        if simr not in formats:
            print(f"[WARN] simulating with {simr} but only {'/'.join(formats)} was exported, "
                  f"so the testbench may not find its DUT netlist (use --format {simr} or both)",
                  file=sys.stderr)
        sweep = None                    # the model is only valid where it was fitted
        if last_res.freq is not None and len(last_res.freq):
            sweep = (float(last_res.freq[0]), float(last_res.freq[-1]))
        result = _run_testbench(args.simulate, simr, args.show_output, sweep, args.timeout)
        if result:
            try:
                sim = io.load_ngspice_sim(result)
                print(f"[ OK ] imported simulation {os.path.basename(result)}")
            except Exception as exc:                      # noqa: BLE001
                print(f"[WARN] could not parse {result}: {exc}", file=sys.stderr)
                rc = rc or 1
        else:
            rc = rc or 1
    if args.plot is not None and last_res is not None and last_res.model_s is not None:
        req = (_default_sparams(last_res.n_ports) if args.plot == "auto"
               else [s.strip() for s in args.plot.split(",") if s.strip()])
        sel = _valid_sparams(req, last_res.n_ports)
        if sel:
            try:
                _show_plots(last_res, sim, sel)
            except Exception as exc:                      # noqa: BLE001
                print(f"[WARN] could not display plots (a display is needed): {exc}",
                      file=sys.stderr)
    return rc


def build_parser():
    p = argparse.ArgumentParser(
        prog="snp2le -b", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Touchstone S-parameters to a lumped-element netlist")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert one or more .sNp files",
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    c.add_argument("inputs", nargs="+", help=".sNp file(s) or glob(s)")
    # mode and model
    c.add_argument("--mode", choices=["universal", "structure"], default="universal")
    c.add_argument("--structure", default=None,
                   help="structure key when --mode structure (see list-structures, default "
                        "inductor-pi)")
    # universal-mode options
    c.add_argument("--order", type=_order, default=6,
                   help="max model order, 2 or more (universal, default 6)")
    c.add_argument("--passive", action="store_true", default=True,
                   help="enforce passivity (universal, default on)")
    c.add_argument("--no-passive", dest="passive", action="store_false")
    c.add_argument("--passivity-ceiling", dest="passivity_ceiling", type=_passivity_ceiling,
                   default=None, metavar="SIGMA",
                   help=f"largest singular value the enforced model may keep, "
                        f"{universal.PASSIVITY_CEILING_MIN:.1f} to "
                        f"{universal.PASSIVITY_CEILING_MAX:.1f}. Universal mode, needs "
                        f"--passive. Default "
                        f"{universal.PASSIVITY_CEILING_DEFAULT:.1f} (strictly passive)")
    c.add_argument("--thermal-noise", dest="thermal_noise", action="store_true",
                   default=False,
                   help="add the passive's thermal noise, kT(I - S S^H) at the ports, as a "
                        "generator computed from the fit. Universal mode, needs a strictly "
                        "passive model, else nothing is written. Default off (noiseless)")
    c.add_argument("--no-thermal-noise", dest="thermal_noise", action="store_false",
                   help="emit the noiseless (ideal) model, the default")
    c.add_argument("--dc-pin", dest="dc_pin", action="store_true", default=None,
                   help="pin the model to the file's 0 Hz sample with a correction below "
                        "--dc-pin-fc, so its DC admittance (a coil's DC resistance) is the "
                        "file's. Default on for a file with a 0 Hz sample")
    c.add_argument("--no-dc-pin", dest="dc_pin", action="store_false",
                   help="leave the model's DC point to the fit, which extrapolates to it")
    c.add_argument("--dc-pin-fc", dest="dc_pin_fc", type=_corner, default=None,
                   metavar="FREQ",
                   help=f"corner of the DC pin's low-pass, e.g. 1kHz. Below it the "
                        f"correction acts, above it the band moves by about fc / f. Default "
                        f"{ConverterState.dc_pin_fc:g} Hz")
    c.add_argument("--dc-island-leak", dest="dc_island_leak", type=_leak, default=None,
                   metavar="S",
                   help="conductance to ground [S] for each DC mode without a DC path, which "
                        "can help harmonic balance converge. Default 0")
    # structure-mode options
    c.add_argument("--fext", type=_freq, default=None, metavar="FREQ",
                   help="extraction frequency, e.g. 7GHz (structure, default 10GHz)")
    c.add_argument("--stages", type=_stages, default=None,
                   help="RLGC ladder cells, 1 to 10 (tline-rlgc, default 2)")
    # fit band (both modes): restrict the data the model is fitted to
    c.add_argument("--fmin", type=_band_edge, default=None, metavar="FREQ",
                   help="lowest frequency used for the fit, e.g. 110GHz "
                        "(default: the file's first point)")
    c.add_argument("--fmax", type=_band_top, default=None, metavar="FREQ",
                   help="highest frequency used for the fit, e.g. 170GHz "
                        "(default: the file's last point)")
    c.add_argument("--iso-r", dest="iso_r", action="store_true", default=True,
                   help="include the in-phase Wilkinson's isolation R or the branch-line "
                        "coupler's arm loss (default on)")
    c.add_argument("--no-iso-r", dest="iso_r", action="store_false")
    # wideband inductor fit (inductor-wideband, inductor-ct)
    seg_lo, seg_hi = inductor_fit.SEGMENT_RANGE
    c.add_argument("--basic", action="store_true", default=False,
                   help="fixed basic topology: 1 coil segment, 1 skin section, no substrate "
                        "coupling (inductor-wideband, inductor-ct)")
    c.add_argument("--segments", type=_coil_segments, default=None, metavar="N",
                   help=f"fixed coil segment count, {seg_lo} to {seg_hi}, per half for "
                        f"inductor-ct (default: the fit picks the fewest of 1 to 3 within "
                        f"10 %% of the best)")
    c.add_argument("--substrate", choices=inductor_fit.SUBSTRATE_CHOICES, default="auto",
                   help="substrate network (default auto: symmetric where the data is, "
                        "coupling only where needed and plausible). inductor-ct takes "
                        "auto, symmetric or asymmetric")
    c.add_argument("--peak-q-weight", type=_positive, nargs="?", metavar="A", default=None,
                   const=inductor_fit.DEFAULT_PEAK_Q_WEIGHT,
                   help=f"weight L and Q up to 1+A times where the data's Q is at least "
                        f"{inductor_fit.PEAK_Q_LEVEL} x its peak, e.g. for a VCO tank "
                        f"(A = {inductor_fit.DEFAULT_PEAK_Q_WEIGHT:g} without a value)")
    c.add_argument("--shunt-accuracy", type=_positive, nargs="?", metavar="K", default=None,
                   const=inductor_fit.DEFAULT_SHUNT_ACCURACY,
                   help=f"measure substrate errors against at least K x the series branch, "
                        f"for measured or FDTD data (K = "
                        f"{inductor_fit.DEFAULT_SHUNT_ACCURACY:g} without a value)")
    c.add_argument("--ct-port", type=int, choices=(1, 2, 3), default=None,
                   help="center tap port of inductor-ct (default: detected from the data)")
    # output
    c.add_argument("--format", choices=["ngspice", "vacask", "both"], default="ngspice",
                   help="output dialect(s), default ngspice. VACASK writes .inc")
    c.add_argument("-o", "--output", default=None, help="output path (single input)")
    c.add_argument("--values", action="store_true", help="print the extracted element values")
    c.add_argument("--tolerances", action="store_true",
                   help="print per-element tolerances at f_ext (extracted structures)")
    c.add_argument("--quiet", action="store_true",
                   help="suppress the per-file status and note: lines and the progress bar. "
                        "[FAIL] and [WARN] lines stay, and with several inputs each file's "
                        "tables keep its name")
    c.add_argument("--progress", action="store_true", default=None,
                   help="show a progress bar while converting (default: only on a terminal)")
    c.add_argument("--no-progress", dest="progress", action="store_false",
                   help="never show the progress bar")
    # simulate a testbench and plot
    c.add_argument("--simulate", metavar="SCH", help="run an Xschem testbench after converting")
    c.add_argument("--simulator", choices=["ngspice", "vacask"], default=None,
                   help="simulator for --simulate (default: auto from the .sch name)")
    c.add_argument("--show-output", action="store_true",
                   help="show the simulator console and plot windows during the run")
    c.add_argument("--timeout", type=_seconds, default=180.0, metavar="S",
                   help="seconds to wait for a --simulate result (default 180)")
    c.add_argument("--plot", nargs="?", const="auto", default=None, metavar="SPARAMS",
                   help="display data-vs-model plots (optional comma list, e.g. S11,S21)")
    c.set_defaults(func=cmd_convert)

    sub.add_parser("list-structures", help="list available structure keys")
    return p


def main(argv=None):
    # Value rows print unit symbols like Ω and µ.  On Windows consoles with a legacy
    # code page (cp1252/cp437) the default 'strict' encoding would crash the print,
    # so degrade unencodable characters to '?' instead.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, OSError):
            pass
    args = build_parser().parse_args(argv)
    if args.cmd == "list-structures":
        for key, name, nports in structure_items():
            print(f"{key:18s} {name}  ({nports}-port)")
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
