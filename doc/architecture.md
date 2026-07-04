# snp2le: architecture and developer notes

For what the tool does and how to install and run it, see the main
[README](../README.md). This file covers what the README does not: how the code
is organised, the data flow, how to extend it, and the internal caveats.

`snp2le` is one package split into a pure-Python, Qt-free `snp2le.core` (fully
testable) and a thin PySide6 `snp2le.gui`, wired together by the single entry
point `engine.convert(state, net)`. The module map is the README's
[Directory Structure](../README.md#directory-structure).


## Data flow

The flow is always **load, `engine.convert(state, net)`, `Results`, views**:

1. `io.load_touchstone` reads the `.sNp` (scikit-rf) and drops any 0 Hz sample.
2. `engine.convert(state, net)` runs the chosen mode and returns a `Results`
   dataclass: the IR, both rendered netlists, the data-vs-model S-parameters,
   element values, tolerances and messages.
3. The GUI (`design_view`, `plot_view`) and the CLI both render from that one
   `Results`, so what you see and what you export always agree.


## Adding a structure

Subclass `snp2le.core.structures.base.Structure`, implement `extract(net, ...)`
returning `(CircuitIR, metrics, rows)`, and register it in
`snp2le/core/structures/__init__.py`. It then appears in the GUI dropdown and the
CLI automatically.


## Developing

Install with the dev extras (pytest, build, twine) on top of the runtime
dependencies, then run the tests:

```bash
pip install -e ".[dev]"
pytest
```


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
