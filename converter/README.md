# snp2le — S-Parameter to Lumped-Element Netlist Converter

Convert a Touchstone `.sNp` S-parameter file (e.g. from an AWS Palace EM
simulation) into an equivalent **lumped-element netlist** for **Ngspice**
(Berkeley SPICE3) and **VACASK** (Spectre syntax), so an EM-extracted structure
can be co-simulated at circuit level without re-running the field solve.

Built with the same architecture and look as the JKU LPF designer: a pure-Python,
Qt-free `core/` (fully testable) and a thin PySide6 `gui/`, both driven by one
entry point — `engine.convert(state, net)`.

---

## Two conversion modes

* **Universal (any N-port)** — vector-fits the S-parameters (scikit-rf
  `VectorFitting`), optionally enforces passivity, and synthesises a passive
  macromodel (R, C + controlled sources). Works for any structure and port
  count; electrically exact, but not physically interpretable.
* **Structure-specific** — fits a known physical topology so every component maps
  to reality. Available models (all 2-port, inspired by Volker Muehlhaus'
  *lumpedmodel*):
  * **Inductor (π-model)** — series R-L, shunt C/R each port; extracted at peak-Q.
  * **MIM capacitor** — series C with parasitic L/R, plus shunt C each port.
  * **Transmission line (RLGC)** — an N-cell π-ladder from γℓ and Z_c (ABCD).

A single dialect-agnostic Circuit IR drives both netlist backends and the
schematic, so the outputs always agree.

---

## Quick start (VSCode)

```bash
# 1. create and activate a virtual environment
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate

# 2. install dependencies
pip install -r requirements.txt

# 3. run the GUI
python app.py

# 4. run the tests
pytest -q            # or:  python tests/test_core.py
```

A demo 2-port is preloaded on first run; `examples/ind_demo.s2p` is included.

### Recommended VSCode setup
* Select the `.venv` interpreter (Command Palette → *Python: Select Interpreter*).
* Extensions: *Python* + *Pylance*. Optional: *Ruff* for linting.
* The package is plain (no install step); run `app.py` from the project root so
  `core` and `gui` resolve.

---

## Command line (for Makefiles / batch)

```bash
python cli.py convert coupler.s4p --mode universal --order 12 --format ngspice -o coupler.cir
python cli.py convert ind.s2p --mode structure --structure inductor-pi --format both
python cli.py convert "*.s2p" --mode universal --format both
python cli.py list-structures
```

`--format both` writes a `.cir` (Ngspice) and a `.scs` (VACASK). Exit code is
non-zero if any conversion fails, so it drops into a build cleanly.

---

## Project layout

```
snp2le/
├── app.py                 GUI entry point
├── cli.py                 command-line entry point
├── snp2le.spec            PyInstaller build recipe (EXE)
├── requirements.txt
├── core/                  pure Python, no Qt — all the maths
│   ├── io.py              load Touchstone (scikit-rf), summarise, drop DC
│   ├── units.py           engineering-notation parse/format
│   ├── ir.py              dialect-agnostic Circuit IR (element list)
│   ├── netlist.py         IR → Ngspice (SPICE3) and VACASK (Spectre); skrf parser
│   ├── universal.py       vector-fit macromodel (passivity, model reconstruction)
│   ├── mna.py             RLC IR → N-port S-parameters (model overlay)
│   ├── structures/        physical extractors
│   │   ├── base.py        Structure ABC  → (ir, metrics, rows)
│   │   ├── inductor_pi.py · mim_cap.py · tline.py
│   │   └── __init__.py    registry
│   ├── state.py           ConverterState + Results dataclasses
│   └── engine.py          convert(state, net) → Results   ← single entry point
├── gui/                   PySide6 — no maths
│   ├── style.py           JKU-palette stylesheet
│   ├── logo.py            snp2le logo/icon
│   ├── footer.py          JKU / IICQC / © Simon Dorrer
│   ├── widgets.py         math labels, output fields, section titles
│   ├── schematic_widget.py · mpl_style.py · help_dialog.py
│   ├── top_bar.py         load + mode + structure + order + view + help
│   ├── design_view.py     result · values · schematic · netlist
│   ├── plot_view.py       4× S-parameter data-vs-model (mag + phase)
│   ├── main_window.py     the controller
│   └── assets/            logos (svg + png), snp2le.ico
├── tools/                 make_logos.py · make_icon.py (dev helpers)
├── tests/                 test_core.py (pytest)
└── examples/              ind_demo.s2p
```

The data flow is always **load → `engine.convert(state, net)` → `Results` → views**.
To add a structure, subclass `core/structures/base.Structure`, implement
`extract(net) → (CircuitIR, metrics, rows)`, and register it in
`core/structures/__init__.py`. It then appears in the GUI dropdown and the CLI
automatically.

---

## Building a standalone executable (.exe)

Yes — `snp2le.spec` is a [PyInstaller](https://pyinstaller.org) recipe, just like
the `.spec` from your previous design. It bundles the logos and the lazy
scikit-rf / schemdraw / matplotlib data files.

```bash
pip install pyinstaller cairosvg pillow
python tools/make_icon.py          # optional: build gui/assets/snp2le.ico
pyinstaller snp2le.spec            # output in dist/snp2le/
```

* Result: `dist/snp2le/snp2le.exe` (Windows) or `dist/snp2le/snp2le` (macOS/Linux)
  — a folder you can zip and hand over. Run it on a machine **without** Python.
* For a **single file** instead of a folder, set `ONEFILE = True` near the top of
  `snp2le.spec` (bigger, slower first launch, but one `.exe`).
* Build on the OS you target — PyInstaller does not cross-compile (build the
  Windows `.exe` on Windows).
* If first launch is slow or a module is missing, add it to `hiddenimports` in the
  spec; scikit-rf occasionally needs an extra `scipy` submodule.
* `console=False` hides the terminal window; set it to `True` temporarily if you
  need to see tracebacks while debugging the build.

---

## Notes / limitations

* Verification of the final netlist (re-simulating it against the original) is
  done in your own flow (Xschem / Ngspice / VACASK) and is intentionally out of
  scope here.
* The VACASK (Spectre) controlled-source syntax (`vccs` / `cccs`) should be
  checked against your VACASK build.
* `is_passive()` may report borderline-False even after enforcement on a good fit;
  the model is still usable. The status is reported honestly ("near-passive").
* A 0 Hz (DC) sample is dropped automatically, since it breaks the
  Y-/ABCD-parameter extraction and the MNA rebuild.
* The transmission-line ladder uses 4 π-cells by default (`N_SEGMENTS` in
  `core/structures/tline.py`).

© Simon Dorrer · IICQC, JKU Linz
