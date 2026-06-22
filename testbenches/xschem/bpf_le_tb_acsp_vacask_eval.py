# bpf_le_tb_acsp_vacask_eval.py
#
# VACASK postprocessing script for the bpf_le acsp (AC S-parameter) testbench.
# Invoked from the testbench control block via:
#     postprocess(PYTHON, "../bpf_le_tb_acsp_vacask_eval.py")
#
# It reads VACASK's raw output, then:
#   * plots |S11|,|S21|,|S12|,|S22| in dB and their phase in degrees -> a PNG, and
#   * writes sim_data/bpf_le_tb_acsp_vacask.txt in the same column layout the ngspice
#     testbench produces, so snp2le's "Import simulation" / auto-import picks it up.
#
# VACASK ships rawfile.py on the postprocess Python path (the IIC reference scripts
# also do `from rawfile import rawread`).
import os
import sys
import glob
import numpy as np

import matplotlib
if not os.environ.get("SHOW_PLOTS"):          # headless under VACASK's run loop
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

from rawfile import rawread

TB = "bpf_le_tb_acsp_vacask"

try:
    HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                              # exec'd without __file__
    HERE = os.getcwd()


def find_raw():
    """Newest .raw VACASK wrote (cwd is the netlist dir during the run)."""
    cands = []
    for d in (os.getcwd(), os.path.join(HERE, "simulations"), HERE):
        cands += glob.glob(os.path.join(d, "*.raw"))
    cands = [c for c in cands if os.path.isfile(c)]
    if not cands:
        sys.exit("postprocess: no .raw output found (looked in cwd and ./simulations)")
    return max(cands, key=os.path.getmtime)


def load_acsp(raw):
    """Return the (frequency, S-dict) of the acsp analysis in `raw`.

    The acsp output names the S-parameters s(i,j) (port i out, port j excited)."""
    rd = rawread(raw)
    plots = None
    for ndx in range(8):                       # skip an op plot if one precedes acsp
        try:
            p = rd.get(ndx=ndx, sweeps=0)
            _ = p["frequency"]
            plots = p
            break
        except Exception:
            continue
    if plots is None:
        plots = rd.get(sweeps=0)

    def sij(i, j):
        for nm in (f"s({i},{j})", f"S({i},{j})", f"s_{i}_{j}", f"S_{i}_{j}"):
            try:
                return np.asarray(plots[nm]).astype(complex).ravel()
            except Exception:
                continue
        raise KeyError(f"S({i},{j}) not found in {raw}")

    f = np.real(np.asarray(plots["frequency"]).astype(complex)).ravel()
    S = {"S11": sij(1, 1), "S21": sij(2, 1), "S12": sij(1, 2), "S22": sij(2, 2)}
    return f, S


def write_table(f, dB, deg):
    """Write sim_data/<TB>.txt in the ngspice-testbench column layout."""
    repo = os.path.abspath(os.path.join(HERE, "..", ".."))
    out_dir = os.path.join(repo, "sim_data")
    os.makedirs(out_dir, exist_ok=True)
    cols = ["frequency", "s11_db", "s22_db", "s12_db", "s21_db",
            "s11_deg", "s22_deg", "s12_deg", "s21_deg"]
    data = np.column_stack([f, dB["S11"], dB["S22"], dB["S12"], dB["S21"],
                            deg["S11"], deg["S22"], deg["S12"], deg["S21"]])
    path = os.path.join(out_dir, TB + ".txt")
    with open(path, "w") as fh:
        fh.write(" " + " ".join(f"{c:>15s}" for c in cols) + "\n")
        for row in data:
            fh.write(" " + " ".join(f"{x: .8e}" for x in row) + "\n")
    return path


def main():
    raw = find_raw()
    f, S = load_acsp(raw)
    dB = {k: 20.0 * np.log10(np.maximum(np.abs(v), 1e-300)) for k, v in S.items()}
    deg = {k: np.unwrap(np.angle(v)) * 180.0 / np.pi for k, v in S.items()}

    table = write_table(f, dB, deg)
    print(f"postprocess: wrote {table}")

    fig, (axm, axp) = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    fghz = f / 1e9
    for k in ("S11", "S21", "S12", "S22"):
        axm.plot(fghz, dB[k], label=k)
        axp.plot(fghz, deg[k], label=k)
    axm.set_title("bpf_le - VACASK acsp S-parameters")
    axm.set_ylabel("magnitude (dB)"); axm.grid(True, alpha=0.3)
    axm.legend(ncol=4, fontsize=8)
    axp.set_ylabel("phase (deg)"); axp.set_xlabel("frequency (GHz)")
    axp.grid(True, alpha=0.3)
    fig.tight_layout()
    png = os.path.join(os.path.dirname(table), TB + ".png")
    fig.savefig(png, dpi=130)
    print(f"postprocess: wrote {png}")
    if os.environ.get("SHOW_PLOTS"):
        plt.show()


try:
    main()
except Exception as exc:                       # don't crash VACASK's run loop
    print(f"postprocess failed: {exc}", file=sys.stderr)
