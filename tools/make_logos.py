#!/usr/bin/env python3
"""make_logos.py - rasterise the footer SVG logos to transparent PNGs.

QtSvg renders Inkscape SVGs unreliably, so the footer loads pre-rasterised PNGs.
Run this whenever gui/assets/jku.svg or iicqc.svg change:

    python tools/make_logos.py

Requires cairosvg (pip install cairosvg).
"""
from __future__ import annotations
import os

import cairosvg

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(HERE, "snp2le", "gui", "assets")

JOBS = [("jku.svg", "jku.png", 96), ("iicqc.svg", "iicqc.png", 78)]


def main():
    for src, out, height in JOBS:
        s = os.path.join(ASSETS, src)
        o = os.path.join(ASSETS, out)
        if not os.path.exists(s):
            print(f"skip {src} (missing)")
            continue
        cairosvg.svg2png(url=s, write_to=o, output_height=height,
                         background_color="rgba(0,0,0,0)")
        print(f"{src} -> {out}  (h={height}, transparent)")


if __name__ == "__main__":
    main()
