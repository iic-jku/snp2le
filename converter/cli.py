#!/usr/bin/env python3
"""cli.py - command-line interface for batch / scripted use.

    # universal macromodel -> ngspice netlist
    snp2le convert coupler.s4p --mode universal --order 12 -o coupler.spice

    # structure extraction at 7 GHz, both dialects, print values + tolerances
    snp2le convert ind.s2p --mode structure --structure inductor-pi \\
        --fext 7GHz --format both --values --tolerances

    # convert, run an Xschem testbench, and show data-vs-model-vs-sim plots
    snp2le convert bpf.s2p --mode universal --order 13 -o bpf_le.spice \\
        --simulate testbenches/xschem/bpf_le_tb_acsp_ngspice.sch --plot

Globs are expanded; with --format both, two files are written per input.  Exit
code is non-zero if any conversion (or a requested simulation) fails.
"""
from __future__ import annotations
import argparse
import glob
import os
import sys

from core import io, engine, units
from core.state import ConverterState
from core.structures import structure_items


def _out_path(src, explicit, dialect, n_inputs, n_formats):
    ext = "inc" if dialect == "vacask" else "spice"          # VACASK = .inc
    if explicit and n_inputs == 1 and n_formats == 1:
        return explicit
    base = os.path.splitext(os.path.basename(explicit or src))[0]
    return f"{base}.{ext}"


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
    return (["S11"] + [f"S{i}1" for i in range(2, n + 1)])[:4]   # match + couplings


def _run_testbench(sch, simulator, show_output):
    """Run an Xschem testbench with `simulator`; return the result file in sim_data."""
    import subprocess
    import time
    from core import xschem
    if not xschem.available():
        print("xschem not found on PATH - cannot run a testbench", file=sys.stderr)
        return None
    sch = os.path.abspath(sch)
    if not os.path.isfile(sch):
        print(f"testbench not found: {sch}", file=sys.stderr)
        return None
    prog, args, cwd = xschem.simulate_command(sch, show_output=show_output,
                                              simulator=simulator)
    os.makedirs(os.path.join(cwd, "simulations"), exist_ok=True)
    env = os.environ.copy()
    if simulator == "vacask" and show_output:               # let the postprocess show plots
        env["SHOW_PLOTS"] = "1"
    start = time.time()
    print(f"  running {os.path.basename(sch)} with {simulator}…")
    subprocess.run([prog, *args], cwd=cwd, env=env)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sim_data = os.path.join(repo_root, "sim_data")
    stem = os.path.splitext(os.path.basename(sch))[0]
    non = {".raw", ".spice", ".inc", ".cir", ".net", ".log", ".out",
           ".svg", ".png", ".ps", ".pdf", ".sch"}
    for _ in range(25):                                     # let the result settle
        cands = []
        if os.path.isdir(sim_data):
            for f in os.listdir(sim_data):
                if os.path.splitext(f)[1].lower() in non or not f.startswith(stem):
                    continue
                p = os.path.join(sim_data, f)
                try:
                    if os.path.getmtime(p) >= start - 2 and os.path.getsize(p) > 0:
                        cands.append((os.path.getmtime(p), p))
                except OSError:
                    continue
        if cands:
            return max(cands)[1]
        time.sleep(0.2)
    print(f"  no fresh result for '{stem}' in {sim_data}", file=sys.stderr)
    return None


def _show_plots(res, sim, sparams):
    import numpy as np
    import matplotlib.pyplot as plt
    f = np.asarray(res.freq, float) / 1e9
    data = np.asarray(res.data_s); model = np.asarray(res.model_s)
    n = len(sparams)
    fig, ax = plt.subplots(2, n, figsize=(3.6 * n, 6.0), squeeze=False)
    for c, name in enumerate(sparams):
        i, j = int(name[1]) - 1, int(name[2]) - 1
        d = data[:, i, j]; m = model[:, i, j]
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
        a0.set_title(name); a0.set_ylabel("|S| (dB)"); a0.grid(alpha=.3)
        a1.set_ylabel("phase (deg)"); a1.set_xlabel("f (GHz)"); a1.grid(alpha=.3)
        if c == 0:
            a0.legend(fontsize=8)
    fig.tight_layout()
    plt.show()


def cmd_convert(args):
    paths = []
    for pat in args.inputs:
        paths.extend(sorted(glob.glob(pat)) or [pat])
    if not paths:
        print("no input files", file=sys.stderr)
        return 2

    formats = ["ngspice", "vacask"] if args.format == "both" else [args.format]
    rc = 0
    last_res = None
    for src in paths:
        try:
            net = io.load_touchstone(src)
        except Exception as exc:                          # noqa: BLE001
            print(f"[FAIL] {src}: {exc}", file=sys.stderr); rc = 1; continue
        state = ConverterState(
            mode=args.mode, structure_key=args.structure,
            max_order=args.order, enforce_passivity=args.passive,
            f_extract=args.fext, n_segments=args.stages, iso_resistor=args.iso_r)
        res = engine.convert(state, net)
        if not res.ok:
            print(f"[FAIL] {src}: {res.error}", file=sys.stderr); rc = 1; continue
        last_res = res
        for dialect in formats:
            text = res.vacask if dialect == "vacask" else res.ngspice
            out = _out_path(src, args.output, dialect, len(paths), len(formats))
            with open(out, "w") as fh:
                fh.write(text)
            if not args.quiet:
                extra = (f"rms={res.rms_error:.2e}  poles={res.n_poles}"
                         if res.mode == "universal"
                         else f"f_ext={units.format_eng(res.metrics.get('f_extract'), 'Hz')}")
                print(f"[ OK ] {src} -> {out}  ({dialect}, {extra})")
        if args.values:
            _print_values(res)
        if args.tolerances:
            _print_tolerances(res)

    # optional: run a testbench, then show the data-vs-model(-vs-sim) plots
    sim = None
    if args.simulate:
        simr = args.simulator or ("vacask" if "vacask" in args.simulate.lower() else "ngspice")
        result = _run_testbench(args.simulate, simr, args.show_output)
        if result:
            try:
                sim = io.load_ngspice_sim(result)
                print(f"[ OK ] imported simulation {os.path.basename(result)}")
            except Exception as exc:                      # noqa: BLE001
                print(f"[WARN] could not parse {result}: {exc}", file=sys.stderr)
        else:
            rc = rc or 1
    if args.plot is not None and last_res is not None and last_res.model_s is not None:
        sel = (_default_sparams(last_res.n_ports) if args.plot == "auto"
               else [s.strip().upper() for s in args.plot.split(",") if s.strip()])
        _show_plots(last_res, sim, sel)
    return rc


def build_parser():
    p = argparse.ArgumentParser(
        prog="snp2le", formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Touchstone S-parameters -> lumped-element netlist")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert one or more .sNp files",
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    c.add_argument("inputs", nargs="+", help=".sNp file(s) or glob(s)")
    # mode / model
    c.add_argument("--mode", choices=["universal", "structure"], default="universal")
    c.add_argument("--structure", default="inductor-pi",
                   help="structure key when --mode structure (see list-structures)")
    # universal-mode options
    c.add_argument("--order", type=int, default=6, help="max model order (universal)")
    c.add_argument("--passive", action="store_true", default=True,
                   help="enforce passivity (universal, default on)")
    c.add_argument("--no-passive", dest="passive", action="store_false")
    # structure-mode options
    c.add_argument("--fext", type=units.parse_eng, default=10e9, metavar="FREQ",
                   help="extraction frequency, e.g. 7GHz (structure)")
    c.add_argument("--stages", type=int, default=2, help="RLGC ladder cells (tline-rlgc)")
    c.add_argument("--iso-r", dest="iso_r", action="store_true", default=True,
                   help="include the Wilkinson isolation R / branch-line arm loss")
    c.add_argument("--no-iso-r", dest="iso_r", action="store_false")
    # output
    c.add_argument("--format", choices=["ngspice", "vacask", "both"], default="ngspice")
    c.add_argument("-o", "--output", default=None, help="output path (single input)")
    c.add_argument("--values", action="store_true", help="print the extracted element values")
    c.add_argument("--tolerances", action="store_true", help="print per-element tolerances")
    c.add_argument("--quiet", action="store_true")
    # simulate a testbench + plot
    c.add_argument("--simulate", metavar="SCH", help="run an Xschem testbench after converting")
    c.add_argument("--simulator", choices=["ngspice", "vacask"], default=None,
                   help="simulator for --simulate (default: auto from the .sch name)")
    c.add_argument("--show-output", action="store_true",
                   help="show the simulator's console / plot windows during the run")
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
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
