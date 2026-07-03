# snp2le: architecture and developer notes

This is the architecture / developer reference. For installing and using the tool,
see the main [README](../README.md).

Convert a Touchstone `.sNp` S-parameter file (for example from an AWS Palace EM
simulation) into an equivalent **lumped-element netlist** for **Ngspice**
(Berkeley SPICE3) and **VACASK** (Spectre syntax), so an EM-extracted structure
can be co-simulated at circuit level without re-running the field solve.

The code is a single package, `snp2le`, split into a pure-Python, Qt-free
`snp2le.core` (fully testable) and a thin PySide6 `snp2le.gui`, both driven by one
entry point, `engine.convert(state, net)`.

---

## Two conversion modes

* **Universal (any N-port).** Vector-fits the S-parameters (scikit-rf
  `VectorFitting`), optionally enforces passivity, and synthesises a passive
  macromodel (R, C and controlled sources). Works for any structure and port
  count. Electrically exact, but not physically interpretable.
* **Structure-specific.** Fits a known physical topology so every component maps
  to reality, at a chosen extraction frequency:
  * **Inductor**, **MIM capacitor**, **Transmission line (RLGC)** (2-port),
    inspired by Volker Muehlhaus'
    [lumpedmodel](https://github.com/VolkerMuehlhaus/lumpedmodel).
  * **Wilkinson divider**, in-phase and quadrature (3-port).
  * **Balun (transformer)** and **Branch-line coupler** (4-port).

A single dialect-agnostic Circuit IR drives both netlist backends and the
schematic, so the outputs always agree.

---

## Data flow

The flow is always **load, `engine.convert(state, net)`, `Results`, views**:

1. `io.load_touchstone` reads the `.sNp` (scikit-rf) and drops any 0 Hz sample.
2. `engine.convert(state, net)` runs the chosen mode and returns a `Results`
   dataclass: the IR, both rendered netlists, the data-vs-model S-parameters,
   element values, tolerances and messages.
3. The GUI (`design_view`, `plot_view`) and the CLI both render from that one
   `Results`, so what you see and what you export always agree.

---

## Project layout

```
snp2le/                       repository root
├── pyproject.toml            packaging metadata, dependencies, entry point
├── snp2le.spec               PyInstaller recipe (standalone .exe)
├── snp2le/                   the application package
│   ├── __init__.py           package version
│   ├── __main__.py           entry point: `snp2le` (GUI), `snp2le -b` (CLI)
│   ├── app.py                GUI launcher
│   ├── cli.py                command-line interface
│   ├── core/                 pure Python, no Qt, all the maths
│   │   ├── io.py             load Touchstone (scikit-rf), summarise, drop DC
│   │   ├── units.py          engineering-notation parse/format
│   │   ├── ir.py             dialect-agnostic Circuit IR (element list)
│   │   ├── netlist.py        IR to Ngspice (SPICE3) and VACASK (Spectre)
│   │   ├── universal.py      vector-fit macromodel (passivity, reconstruction)
│   │   ├── mna.py            RLC IR to N-port S-parameters (model overlay)
│   │   ├── dc.py             DC operating-point (singularity) check
│   │   ├── xschem.py         headless Xschem netlist and simulate commands
│   │   ├── structures/       physical extractors, one file per topology
│   │   │   ├── base.py       Structure ABC, returns (ir, metrics, rows)
│   │   │   ├── inductor_pi.py, mim_cap.py, tline.py
│   │   │   ├── wilkinson.py, balun.py, branchline.py
│   │   │   └── __init__.py   registry (GUI dropdown + CLI auto-discover)
│   │   ├── state.py          ConverterState + Results dataclasses
│   │   └── engine.py         convert(state, net) -> Results   (single entry point)
│   ├── gui/                  PySide6, no maths
│   │   ├── style.py, combobox_style.py, mpl_style.py   look and feel
│   │   ├── logo.py, footer.py, widgets.py, schematic_widget.py
│   │   ├── top_bar.py        load + mode + structure + options + simulator + run
│   │   ├── design_view.py    result, values, tolerances, schematic, netlist
│   │   ├── plot_view.py      four S-parameter / extracted-parameter plots
│   │   ├── help_dialog.py, log_dialog.py
│   │   ├── main_window.py    the controller
│   │   └── assets/           logos (svg + png), snp2le.ico
│   └── examples/             bundled Touchstone .sNp sample files
├── tests/                    test_core.py (pytest)
├── tools/                    make_logos.py, make_icon.py (dev helpers)
└── doc/                      this file and screenshots
```

To add a structure, subclass `snp2le.core.structures.base.Structure`, implement
`extract(net, ...)` returning `(CircuitIR, metrics, rows)`, and register it in
`snp2le/core/structures/__init__.py`. It then appears in the GUI dropdown and the
CLI automatically.

---

## Developing

An editable install puts `snp2le` on the path and pulls in every dependency:

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate    macOS/Linux:  source .venv/bin/activate
pip install -e ".[dev]"        # runtime deps plus pytest / build / twine

python -m snp2le               # run the GUI from the source tree
python -m snp2le -b list-structures
pytest                         # run the tests
```

Run the GUI as a module (`python -m snp2le`) from the repo root, not
`python snp2le/app.py` directly: the launcher imports the `snp2le` package, which
Python resolves only when run as a module or after an install.

---

## Building a standalone executable (.exe)

`snp2le.spec` is a [PyInstaller](https://pyinstaller.org) recipe. It bundles the
logos, the examples, and the lazy scikit-rf / schemdraw / matplotlib data files.

```bash
pip install pyinstaller cairosvg pillow
python tools/make_icon.py          # optional: build snp2le/gui/assets/snp2le.ico
pyinstaller snp2le.spec            # output in dist/snp2le/
```

* Result: `dist/snp2le/snp2le.exe` (Windows) or `dist/snp2le/snp2le`
  (macOS/Linux), a folder you can zip and run on a machine **without** Python.
* For a **single file** instead of a folder, set `ONEFILE = True` near the top of
  `snp2le.spec` (bigger, slower first launch, but one `.exe`).
* PyInstaller does not cross-compile, so build on the OS you target.

---

## Notes / limitations

* Verifying the final netlist (re-simulating it against the original) is done in
  your own flow (Xschem / Ngspice / VACASK). The GUI can drive it (Load .sch, Run
  Simulation), but the simulators themselves are not bundled.
* For a universal macromodel the DC operating point is checked. A linear model
  only fails to solve if the network is singular (a floating internal node), and
  the result flags that before you hand the netlist to a simulator.
* In VACASK the subcircuit ground is node `GND` (Spectre has no implicit node-0
  ground), so the testbench must declare `ground GND`. Ngspice keeps node `0`.
  High-order universal fits are conditioned automatically so VACASK reproduces the
  same response as Ngspice.
* `is_passive()` may report borderline-False even after enforcement on a good fit.
  The model is still usable. The status is reported honestly ("near-passive").
* A 0 Hz (DC) sample is dropped automatically, since it breaks the
  Y-/ABCD-parameter extraction and the MNA rebuild.
* The transmission-line ladder uses 2 pi-cells by default (`N_SEGMENTS` in
  `snp2le/core/structures/tline.py`) and can be set from 1 to 10 stages.

---

## Acknowledgements

* The structure-specific extractors (inductor, MIM capacitor, RLGC line) were
  inspired by Volker Muehlhaus'
  [lumpedmodel](https://github.com/VolkerMuehlhaus/lumpedmodel).
* The passivity-enforcement strategy for the universal macromodel (escalate the
  sample count, then fall back to a lower model order) was adapted from the
  [COBRA project](https://github.com/DI-PASSIONATE/COBRA)
  (`src/cobra/spice_sim/vector_fit.py`).
* Vector fitting is provided by [scikit-rf](https://scikit-rf.org).

(c) Simon Dorrer, IICQC, JKU Linz
