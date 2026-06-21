#!/usr/bin/env python3
"""cli.py - command-line interface for batch / Makefile use.

    snp2le convert coupler.s4p --mode universal --order 12 --passive \
        --format ngspice -o coupler.spice
    snp2le convert ind.s2p --mode structure --structure inductor-pi --format both

Globs are expanded; with --format both, two files are written per input.
Exit code is non-zero if any conversion fails.
"""
from __future__ import annotations
import argparse
import glob
import os
import sys

from core import io, engine
from core.state import ConverterState
from core.structures import structure_items
from core.pdk import pdk_items, get_pdk, DEFAULT_PDK


def _out_path(src, explicit, dialect, n_inputs, n_formats):
    ext = "scs" if dialect == "vacask" else "spice"
    if explicit and n_inputs == 1 and n_formats == 1:
        return explicit
    base = os.path.splitext(os.path.basename(explicit or src))[0]
    return f"{base}.{ext}"


def cmd_convert(args):
    paths = []
    for pat in args.inputs:
        paths.extend(sorted(glob.glob(pat)) or [pat])
    if not paths:
        print("no input files", file=sys.stderr)
        return 2

    pdk = get_pdk(args.pdk)
    if not pdk.supported:
        print(f"PDK '{pdk.key}' is not supported yet (see list-pdks)",
              file=sys.stderr)
        return 2
    if "vacask" in (["ngspice", "vacask"] if args.format == "both" else [args.format]) \
            and not pdk.vacask:
        print(f"VACASK output is not available for PDK '{pdk.key}'",
              file=sys.stderr)
        return 2

    formats = ["ngspice", "vacask"] if args.format == "both" else [args.format]
    rc = 0
    for src in paths:
        try:
            net = io.load_touchstone(src)
        except Exception as exc:                          # noqa: BLE001
            print(f"[FAIL] {src}: {exc}", file=sys.stderr); rc = 1; continue
        state = ConverterState(mode=args.mode, structure_key=args.structure,
                               pdk=args.pdk, max_order=args.order,
                               enforce_passivity=args.passive)
        res = engine.convert(state, net)
        if not res.ok:
            print(f"[FAIL] {src}: {res.error}", file=sys.stderr); rc = 1; continue
        for dialect in formats:
            text = res.vacask if dialect == "vacask" else res.ngspice
            out = _out_path(src, args.output, dialect, len(paths), len(formats))
            with open(out, "w") as fh:
                fh.write(text)
            if not args.quiet:
                extra = (f"rms={res.rms_error:.2e}  poles={res.n_poles}"
                         if res.mode == "universal" else "structure")
                print(f"[ OK ] {src} -> {out}  ({dialect}, {extra})")
    return rc


def build_parser():
    p = argparse.ArgumentParser(prog="snp2le",
                                description="Touchstone S-parameters -> lumped-element netlist")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("convert", help="convert one or more .sNp files")
    c.add_argument("inputs", nargs="+", help=".sNp file(s) or glob(s)")
    c.add_argument("--mode", choices=["universal", "structure"], default="universal")
    c.add_argument("--structure", default="inductor-pi",
                   help="structure key (see list-structures)")
    c.add_argument("--pdk", default=DEFAULT_PDK,
                   help="target PDK key (see list-pdks)")
    c.add_argument("--order", type=int, default=6, help="max model order (universal)")
    c.add_argument("--passive", action="store_true", default=True,
                   help="enforce passivity (universal, default on)")
    c.add_argument("--no-passive", dest="passive", action="store_false")
    c.add_argument("--format", choices=["ngspice", "vacask", "both"], default="ngspice")
    c.add_argument("-o", "--output", default=None, help="output path (single input)")
    c.add_argument("--quiet", action="store_true")
    c.set_defaults(func=cmd_convert)

    sub.add_parser("list-structures", help="list available structure keys")
    sub.add_parser("list-pdks", help="list available PDK keys")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "list-structures":
        for key, name, nports in structure_items():
            print(f"{key:16s} {name}  ({nports}-port)")
        return 0
    if args.cmd == "list-pdks":
        for key, name, supported in pdk_items():
            tag = "" if supported else "  (not supported yet)"
            print(f"{key:16s} {name}{tag}")
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
