# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
# plot_n_port_tb_acsp_xyce.py [testbenchname]
#
# Plot the S-parameters of the Xyce acsp (AC S-parameter) testbenches.
#
# Xyce writes S-parameters only as a Touchstone file, so every Xyce acsp testbench exports
# its result with `.LIN ... FILE=` to data/<TB>.sNp (N the port count).  Like its Ngspice
# and VACASK siblings, this one script serves every port count: scikit-rf reads the file,
# and the figure is drawn through sparam_plot, magnitude and phase over frequency in one
# figure per testbench.
#
# Without an argument every *_tb_acsp_xyce Touchstone file in data/ is plotted; with a
# testbench name only that one.  Each figure is written to figures/<TB>.png and the plot
# windows are opened when a display is available (headless, only the PNGs are written).
import glob
import os
import re
import sys

import numpy as np
import skrf

import sparam_plot as sp

# Data and output paths relative to this script (testbenches/xschem/plot_simulations)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
FIGURES_DIR = os.path.join(SCRIPT_DIR, "figures")


def touchstone(tb):
    """The testbench's result file, data/<TB>.sNp for whichever N it has."""
    hits = [p for p in glob.glob(os.path.join(DATA_DIR, tb + ".s*p"))
            if re.fullmatch(r"\.s\d+p", os.path.splitext(p)[1], re.I)]
    if not hits:
        sys.exit(f"no {tb}.sNp in {DATA_DIR} - run the {tb} testbench first (snp2le's "
                 "'Run Simulation', the CLI's --simulate, or xschem directly)")
    return max(hits, key=os.path.getmtime)


def plot_file(tb, plt):
    net = skrf.Network(touchstone(tb))
    with np.errstate(divide="ignore"):                    # an exact zero reads -inf dB
        db = 20 * np.log10(np.abs(net.s))
    deg = np.unwrap(np.angle(net.s), axis=0) * 180.0 / np.pi     # continuous, as its siblings

    def mag(i, j):
        return db[:, i - 1, j - 1]

    def phase(i, j):
        return deg[:, i - 1, j - 1]

    png = sp.plot_sgrid(plt, os.path.join(FIGURES_DIR, tb + ".png"),
                        f"{tb} - Xyce acsp S-parameters", net.f / 1e9, net.nports,
                        mag, phase)
    print(f"plot: wrote {png}")


def main():
    if len(sys.argv) > 2:
        sys.exit(f"usage: {os.path.basename(sys.argv[0])} [testbenchname]")

    if len(sys.argv) == 2:
        tbs = [sys.argv[1]]
    else:                                       # all acsp Xyce results
        tbs = sorted({os.path.splitext(os.path.basename(t))[0] for t in
                      glob.glob(os.path.join(DATA_DIR, "*_tb_acsp_xyce.s*p"))})
        if not tbs:
            sys.exit(f"no *_tb_acsp_xyce.sNp files in {DATA_DIR} - run a testbench first")

    os.makedirs(FIGURES_DIR, exist_ok=True)
    import matplotlib
    import matplotlib.pyplot as plt             # headless, matplotlib falls back to Agg
    sp.set_style(plt)
    for tb in tbs:
        plot_file(tb, plt)
    if matplotlib.get_backend().lower() != "agg":   # no window without a display
        plt.show()


if __name__ == "__main__":
    main()
