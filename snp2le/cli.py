#!/usr/bin/env python3
"""cli.py - command-line interface for batch and scripted use.

    # universal macromodel to an Ngspice netlist
    snp2le -b convert coupler.s4p --mode universal --order 12 -o coupler.spice

    # structure extraction at 7 GHz, both dialects, print values and tolerances
    snp2le -b convert ind.s2p --mode structure --structure inductor-pi \\
        --fext 7GHz --format both --values --tolerances

    # convert, run an Xschem testbench, and show data-vs-model-vs-sim plots
    snp2le -b convert bpf.s2p --mode universal --order 13 \\
        -o netlist/spice/bpf_le.spice \\
        --simulate testbenches/xschem/bpf_le_tb_acsp_ngspice.sch --plot

Globs are expanded.  With --format both, two files are written per input.  The exit code is
non-zero if any conversion or a requested simulation fails.
"""
from __future__ import annotations
import argparse
import glob
import os
import re
import sys

from snp2le.core import io, engine, units, netlist
from snp2le.core.state import ConverterState
from snp2le.core.structures import structure_items

# extensions in sim_data that are never a result table
_NON_DATA = {".raw", ".spice", ".inc", ".cir", ".net", ".log", ".out", ".svg", ".png",
             ".ps", ".pdf", ".sch", ".aborted"}
_DATA_EXTS = {".txt", ".data", ".dat", ".csv"}


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


def _out_path(src, explicit, dialect, n_inputs, n_formats):
    ext = "inc" if dialect == "vacask" else "spice"          # VACASK writes .inc
    if explicit and n_inputs == 1:
        if n_formats == 1:
            return explicit
        return f"{os.path.splitext(explicit)[0]}.{ext}"      # both: keep -o dir + stem
    base = os.path.splitext(os.path.basename(src))[0]         # many inputs: after each source
    return f"{base}.{ext}"


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


def _run_testbench(sch, simulator, show_output, net, timeout):
    """Run an Xschem testbench with `simulator` and return the imported result path, or None.

    Both Ngspice and VACASK are launched detached by xschem (which returns at once with an
    empty console), so the outcome is read the same way for both: sync the sweep to the loaded
    data, then poll for the result while the simulator process is alive.  When the process has
    exited with no result the run failed, and VACASK's captured log and .aborted marker give
    the specific cause."""
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
    if net is not None:                                      # the sweep follows the loaded data
        try:
            xschem.write_sim_range(cwd, float(net.f[0]), float(net.f[-1]))
        except (TypeError, IndexError, ValueError, OSError):
            pass

    sim_data = os.path.join(_repo_root(), "sim_data")
    stem = os.path.splitext(os.path.basename(sch))[0]
    marker = os.path.join(sim_data, stem + ".aborted")
    log = xschem.sim_log_path(sch, simulator) if simulator == "vacask" else None
    for stale in (os.path.join(sim_data, stem + ".txt"), marker):   # a clean run this time
        try:
            os.remove(stale)
        except OSError:
            pass

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
        r = _find_result(sim_data, stem, start)
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
            return os.path.getmtime(marker) >= start - 1
        except OSError:
            return False

    def fail(msg):
        print("  " + msg, file=sys.stderr)
        _tail_log(log, "VACASK console")
        if simulator != "vacask":
            print("  Ngspice keeps no log here; run the testbench directly or open it in "
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
        elif time.time() - start > 12.0:                    # never even started / instant fail
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
    if args.mode == "structure":
        valid = {k for k, _, _ in structure_items()}
        if args.structure not in valid:
            print(f"unknown structure '{args.structure}'. Valid keys: "
                  f"{', '.join(sorted(valid))}", file=sys.stderr)
            return 2

    paths = []
    for pat in args.inputs:
        hits = sorted(glob.glob(pat))
        if not hits and not os.path.exists(pat):
            print(f"[WARN] no file matches '{pat}'", file=sys.stderr)
        paths.extend(hits or [pat])
    if not paths:
        print("no input files", file=sys.stderr)
        return 2
    if args.output and len(paths) > 1:
        print("[WARN] -o is ignored with multiple inputs; each output is named after its "
              "source", file=sys.stderr)

    formats = ["ngspice", "vacask"] if args.format == "both" else [args.format]
    rc = 0
    last_res = None
    last_net = None
    for src in paths:
        try:
            net = io.load_touchstone(src)
        except Exception as exc:                          # noqa: BLE001
            print(f"[FAIL] {src}: {exc}", file=sys.stderr)
            rc = 1
            continue
        state = ConverterState(
            mode=args.mode, structure_key=args.structure,
            max_order=args.order, enforce_passivity=args.passive,
            f_extract=args.fext, n_segments=args.stages, iso_resistor=args.iso_r)
        res = engine.convert(state, net)
        if not res.ok:
            print(f"[FAIL] {src}: {res.error}", file=sys.stderr)
            rc = 1
            continue
        last_res, last_net = res, net
        for dialect in formats:
            out = _out_path(src, args.output, dialect, len(paths), len(formats))
            if res.ir is not None:
                # name the .SUBCKT after the output file (bpf_le.spice -> bpf_le), so a
                # testbench that instantiates that name resolves the .include.  The GUI export
                # does the same.  The default 's_equivalent' would not match the testbench.
                res.ir.name = netlist.safe_subckt_name(
                    os.path.splitext(os.path.basename(out))[0])
                text = (netlist.render_vacask(res.ir) if dialect == "vacask"
                        else netlist.render_ngspice(res.ir))
            else:
                text = res.vacask if dialect == "vacask" else res.ngspice
            try:
                parent = os.path.dirname(os.path.abspath(out))
                os.makedirs(parent, exist_ok=True)
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                print(f"[FAIL] {src} -> {out}: {exc}", file=sys.stderr)
                rc = 1
                continue
            if not args.quiet:
                if res.mode == "universal":
                    dc = ("" if res.dc is None
                          else "  dc=solvable" if res.dc.ok else "  dc=SINGULAR")
                    extra = f"rms={res.rms_error:.2e}  poles={res.n_poles}{dc}"
                else:
                    extra = f"f_ext={units.format_eng(res.metrics.get('f_extract'), 'Hz')}"
                print(f"[ OK ] {src} -> {out}  ({dialect}, {extra})")
        # a singular DC operating point makes the netlist unsimulable, so always warn
        if res.dc is not None and not res.dc.ok:
            print(f"[WARN] {src}: DC operating point may be singular "
                  f"(margin {res.dc.margin:.0e}); try a lower --order or --passive",
                  file=sys.stderr)
        if not args.quiet:
            for m in res.messages:
                print(f"       note: {m}")
        if args.values:
            _print_values(res)
        if args.tolerances:
            _print_tolerances(res)

    # optional: run a testbench, then show the data-vs-model-vs-sim plots
    sim = None
    if args.simulate and last_res is None:
        print("[WARN] no successful conversion; skipping --simulate", file=sys.stderr)
    elif args.simulate:
        if len(paths) > 1:
            print("[WARN] --simulate uses the last converted file; the testbench's DUT must "
                  "match it", file=sys.stderr)
        simr = args.simulator or ("vacask" if "vacask" in args.simulate.lower() else "ngspice")
        if simr not in formats:
            print(f"[WARN] simulating with {simr} but only {'/'.join(formats)} was exported; "
                  f"the testbench may not find its DUT netlist (use --format {simr} or both)",
                  file=sys.stderr)
        result = _run_testbench(args.simulate, simr, args.show_output, last_net, args.timeout)
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
    c.add_argument("--structure", default="inductor-pi",
                   help="structure key when --mode structure (see list-structures)")
    # universal-mode options
    c.add_argument("--order", type=int, default=6, help="max model order (universal)")
    c.add_argument("--passive", action="store_true", default=True,
                   help="enforce passivity (universal, default on)")
    c.add_argument("--no-passive", dest="passive", action="store_false")
    # structure-mode options
    c.add_argument("--fext", type=_freq, default=10e9, metavar="FREQ",
                   help="extraction frequency, e.g. 7GHz (structure)")
    c.add_argument("--stages", type=_stages, default=2,
                   help="RLGC ladder cells, 1 to 10 (tline-rlgc)")
    c.add_argument("--iso-r", dest="iso_r", action="store_true", default=True,
                   help="include the Wilkinson isolation R or branch-line arm loss")
    c.add_argument("--no-iso-r", dest="iso_r", action="store_false")
    # output
    c.add_argument("--format", choices=["ngspice", "vacask", "both"], default="ngspice")
    c.add_argument("-o", "--output", default=None, help="output path (single input)")
    c.add_argument("--values", action="store_true", help="print the extracted element values")
    c.add_argument("--tolerances", action="store_true", help="print per-element tolerances")
    c.add_argument("--quiet", action="store_true", help="suppress the per-file status line")
    # simulate a testbench and plot
    c.add_argument("--simulate", metavar="SCH", help="run an Xschem testbench after converting")
    c.add_argument("--simulator", choices=["ngspice", "vacask"], default=None,
                   help="simulator for --simulate (default: auto from the .sch name)")
    c.add_argument("--show-output", action="store_true",
                   help="show the simulator console and plot windows during the run")
    c.add_argument("--timeout", type=float, default=180.0, metavar="S",
                   help="seconds to wait for a --simulate result (default 180)")
    c.add_argument("--plot", nargs="?", const="auto", default=None, metavar="SPARAMS",
                   help="display data-vs-model plots (optional comma list, e.g. S11,S21)")
    c.set_defaults(func=cmd_convert)

    sub.add_parser("list-structures", help="list available structure keys")
    return p


def main(argv=None):
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
