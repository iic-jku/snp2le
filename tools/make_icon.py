#!/usr/bin/env python3
"""make_icon.py - render gui/assets/snp2le_logo.svg to a multi-size Windows .ico.

    python tools/make_icon.py

Requires cairosvg and Pillow (pip install cairosvg pillow).  Used by snp2le.spec
to give the built executable an icon.
"""
from __future__ import annotations
import io
import os

import cairosvg
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(HERE, "snp2le", "gui", "assets", "snp2le_logo.svg")
OUT = os.path.join(HERE, "snp2le", "gui", "assets", "snp2le.ico")


def main():
    png = cairosvg.svg2png(url=SVG, output_width=256, output_height=256)
    img = Image.open(io.BytesIO(png)).convert("RGBA")
    img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                         (128, 128), (256, 256)])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
