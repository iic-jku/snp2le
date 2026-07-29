# plot_n_port_tb_acsp_ngspice.py [testbenchname]
#
# Plot the S-parameter tables of the ngspice acsp (AC S-parameter) testbenches.
#
# In a quiet run (snp2le's "Run Simulation" with "Show output" unticked, or the CLI's
# --simulate without --show-output) the `plot` commands in a testbench's .control block
# are commented out, so nothing is displayed during the run.  Every ngspice acsp
# testbench instead exports its results with wrdata to data/<TB>.txt (`wr_vecnames` +
# `wr_singlescale`: a header line with vector names, then a frequency column plus
# s..._db and s..._deg columns).  Like the VACASK sibling plot_n_port_tb_acsp_vacask.py,
# this one script serves every port count: it reads the header to discover the exported
# vectors (loaded with ngspice2python.loadngspicecol) and reproduces the .control
# block's plots with matplotlib, magnitude and phase over frequency in one figure per
# testbench.
#
# Without an argument every *_tb_acsp_ngspice table in data/ is plotted; with a
# testbench name only that one.  Each figure is written to figures/<TB>.png and the
# plot windows are opened when a display is available (headless, only the PNGs are
# written).
import glob
import os
import re
import sys

import ngspice2python as ng
import sparam_plot as sp

# Data and output paths relative to this script (testbenches/xschem/plot_simulations)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
FIGURES_DIR = os.path.join(SCRIPT_DIR, "figures")


def plot_table(tb, plt):
    table = os.path.join(DATA_DIR, tb + ".txt")
    if not os.path.isfile(table):
        sys.exit(f"{table} not found - run the {tb} testbench first (snp2le's "
                 "'Run Simulation', the CLI's --simulate, or xschem directly)")
    with open(table) as fh:                     # header line holds the vector names
        names = fh.readline().split()
    if not names or names[0].lower() != "frequency":
        sys.exit(f"{table} has scale column '{names[0] if names else ''}', not "
                 "'frequency' - it is not an acsp result table")

    fghz = ng.loadngspicecol(table, names[0]) / 1e9
    bases = [n[:-3] for n in names[1:] if n.endswith("_db")]

    def col(base, suffix):
        name = base + suffix
        return ng.loadngspicecol(table, name) if name in names else None

    # Sort the S-parameters into an S(i,j) grid; columns that are not a plain sIJ go
    # to the extra panel.
    grid, extra = {}, []
    for base in bases:
        m = re.fullmatch(r"s(\d)(\d)", base)
        if m:
            grid[(int(m.group(1)), int(m.group(2)))] = base
        else:
            extra.append((base.upper(), col(base, "_db"), col(base, "_deg")))
    n_ports = max((i for i, _ in grid), default=0)

    def mag(i, j):
        return col(grid[(i, j)], "_db") if (i, j) in grid else None

    def phase(i, j):
        return col(grid[(i, j)], "_deg") if (i, j) in grid else None

    png = sp.plot_sgrid(plt, os.path.join(FIGURES_DIR, tb + ".png"),
                        f"{tb} - ngspice acsp S-parameters", fghz, n_ports,
                        mag, phase, extra)
    print(f"plot: wrote {png}")


def main():
    if len(sys.argv) > 2:
        sys.exit(f"usage: {os.path.basename(sys.argv[0])} [testbenchname]")

    if len(sys.argv) == 2:
        tbs = [sys.argv[1]]
    else:                                       # all acsp ngspice result tables
        tbs = sorted(os.path.splitext(os.path.basename(t))[0] for t in
                     glob.glob(os.path.join(DATA_DIR, "*_tb_acsp_ngspice.txt")))
        if not tbs:
            sys.exit(f"no *_tb_acsp_ngspice.txt tables in {DATA_DIR} - "
                     "run a testbench first")

    os.makedirs(FIGURES_DIR, exist_ok=True)
    import matplotlib
    import matplotlib.pyplot as plt             # headless, matplotlib falls back to Agg
    sp.set_style(plt)
    for tb in tbs:
        plot_table(tb, plt)
    if matplotlib.get_backend().lower() != "agg":   # no window without a display
        plt.show()


if __name__ == "__main__":
    main()
