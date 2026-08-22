# snp2le: architecture and developer notes

For what the tool does and how to install and run it, see the main
[README](../README.md). This file covers what the README does not: how the code
is organised, the data flow, how to extend it, and the internal caveats.

`snp2le` is one package split into a pure-Python, Qt-free `snp2le.core` (fully
testable) and a thin `snp2le.gui` on PySide6-Essentials, wired together by the single entry
point `engine.convert(state, net)`. The module map is the README's
[Directory Structure](../README.md#directory-structure).

The GUI uses only `QtCore`, `QtGui`, `QtWidgets` and `QtSvg`, so the declared
dependency is `PySide6-Essentials`, not the full `PySide6` metapackage — the
latter drags in PySide6-Addons (QtWebEngine, Multimedia, Charts, ...), roughly
400 MB that nothing here imports. This matters for container images such as
IIC-OSIC-TOOLS. Keep it that way: a bare `from PySide6.QtCharts import ...`
would still work on a developer machine that happens to have the metapackage
installed, but would break an Essentials-only deployment. A full `PySide6`
install satisfies the requirement too, since the metapackage depends on
`PySide6-Essentials`.


## Data flow

The flow is always **load, `engine.convert(state, net)`, `Results`, views**:

1. `io.load_touchstone` reads the `.sNp` (scikit-rf); `engine.convert` then drops
   any 0 Hz sample through `io.without_dc`.
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
* Passivity is also reported as a number. `universal.max_singular_value()` returns
  the largest singular value of the fitted S-matrix over a grid that spans four
  decades either side of the data and is refined inside the violation bands
  `passivity_test()` reports. `ConverterState.passivity_ceiling` (1.0 to 1.2) is the
  sigma_max the enforcement works towards, not merely an acceptance threshold: the
  model really is perturbed down to it, which trades a bounded violation for a fit up
  to a few times more accurate than strict enforcement gives. sigma_max(S) <= t is
  exactly sigma_max(S/t) <= 1, so `universal._enforce_at()` scales the rational model
  by 1/t, runs scikit-rf's standard perturbation, and scales back. At t = 1.0 both
  scalings are the identity, which is what keeps the strict path bit-for-bit what it
  was. A ceiling the residue perturbation cannot reach (an unbounded violation band,
  from a non-passive constant term) leaves the accurate fit in place instead. 1.0 is
  the floor because a lossless reciprocal network sits at exactly 1. An out-of-range
  number is clamped to the edge it overshot and a non-number falls back to the default
  (`universal.clamp_passivity_ceiling()`), so the GUI field answers "what is the limit"
  by showing it. The rule that the ceiling applies only while enforcing lives in
  `universal.effective_ceiling()` alone, so the GUI, the CLI and the engine cannot
  disagree about it.
* A 0 Hz (DC) sample is dropped automatically, since it breaks the
  Y-/ABCD-parameter extraction and the MNA rebuild.
* The transmission-line ladder uses 2 L-cells by default (`N_SEGMENTS` in
  `snp2le/core/structures/tline.py`) and can be set from 1 to 10 stages.
