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
   any 0 Hz sample through `io.without_dc` and restricts the data to the requested
   fit band through `io.restrict_band` (`state.f_min` / `state.f_max`, both optional).
   Everything downstream, the RMS error, the plots and a testbench run's sweep,
   refers to the fitted band.
2. `engine.convert(state, net)` runs the chosen mode and returns a `Results`
   dataclass: the IR, both rendered netlists, the data-vs-model S-parameters,
   element values, tolerances and messages.
3. The GUI (`design_view`, `plot_view`) and the CLI both render from that one
   `Results`, so what you see and what you export always agree.


## Progress and threading

`engine.convert(state, net, progress=None)` takes an optional
`callback(fraction, message)` and reports an overall 0..1 along the way.
`core/progress.py` holds the two pieces around that contract: `StageTracker`
maps a stage's own 0..1 onto its weighted slice of the whole run (the weights
live in `engine._PLAN_UNIVERSAL` / `_PLAN_STRUCTURE`), and `ProgressReporter` is
a thread-safe sink that also keeps elapsed time and an ETA. Core stays Qt-free:
the reporter is plain `threading`.

Two parts of the pipeline report from inside, which is what makes the fraction
track real work rather than count steps:

* `mna.rlc_sparams` reports per frequency (one MNA solve each), which dominates
  a structure-mode conversion over a wide EM sweep.
* `universal._fit_watch` reports during `auto_fit`. scikit-rf offers no callback
  there, but it appends to `vf.d_res_history` once per pole-relocation
  iteration, so a watcher thread polls that length. It is a real signal and
  needs no log scraping, which is the brittle route `_enforce_passivity`
  already avoids. The iteration count is not known in advance, so the reported
  fraction follows a saturating curve and deliberately stops short of 1.

On the GUI side, `gui/fit_runner.py` runs `engine.convert` on a `QThread` and
`gui/fit_status.py` renders the indicator. It is hosted twice, in the Design
view's Conversion panel and (compact) in the Plot view's header row, so a
running fit is visible in either view without either one growing: both hosts had
spare room. `MainWindow._fit_indicators` is the list the tick drives. Two rules
there:

* **One fit at a time, newest wins.** A request arriving mid-fit is remembered,
  not queued, so dragging a spin box starts one more conversion, not one per
  value. `MainWindow._res` caches the finished `Results`, and Export writes
  that instead of re-converting on the GUI thread.
* **Progress is sampled, not pushed.** The worker updates the reporter and
  `MainWindow._fit_clock` reads `snapshot()` every 80 ms. No Qt signal crosses
  the thread boundary except `finished`, and the elapsed display keeps ticking
  even while the fit sits inside one long scikit-rf call.

A QThread destroyed while running aborts the process, so `FitRunner.shutdown()`
waits, and parks a worker that outlives the wait in `fit_runner._ORPHANS`.


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
* `ConverterState.max_order` is a model order, `n_real + 2 x n_complex`, and it reaches
  scikit-rf as `auto_fit(model_order_max=...)`. `Results.n_poles` counts pole entries,
  where a complex-conjugate pair is one, so the reported number is at most the requested
  order and normally below it. Below scikit-rf 1.12 `model_order_max` was only the exit
  test of the pole-growth loop and never applied to the initial pole set (3 real plus 3
  complex, order 9), so any cap under 9 was inert and a cap above it could be overshot by
  one batch of added pairs. `universal._auto_fit()` passes the initial counts 1.12 would
  compute itself, which fixes the first half on older versions and is inert on 1.12, and
  the second half is why the dependency floor is `scikit-rf>=1.12`.
* Resistor thermal noise is keyed on `ir.physical` (`netlist.py`): a universal
  macromodel's resistors are fit artifacts and are emitted with `noisy=0` in both
  dialects, while a structure model's resistors are real loss and keep their noise.
  The reasoning and the measured numbers are in the comment block above
  `netlist._NOISY_OFF`.
* The bundled `netlist/` examples are `bpf_ihp-sg13g2.s2p` at `--order 13`
  (`two_port`), `wpd_ihp-sg13g2.s3p` at `--order 13` (`three_port`) and
  `blc_ihp-sg13g2.s4p` at `--order 8` (`four_port`), exported with `--format both`.
  The rendered float tails depend on the BLAS the fit ran on, so a regeneration on
  another platform can differ in the last digits without anything being wrong.
* A 0 Hz (DC) sample is dropped automatically, since it breaks the
  Y-/ABCD-parameter extraction and the MNA rebuild.
* The transmission-line ladder uses 2 L-cells by default (`N_SEGMENTS` in
  `snp2le/core/structures/tline.py`) and can be set from 1 to 10 stages.
* `fit_universal` wraps the fit in `contextlib.redirect_stdout/stderr` to
  swallow scikit-rf's chatter, and those rebind `sys.stdout` / `sys.stderr` for
  the whole process, not for one thread. That was harmless while the fit blocked
  the GUI thread (nothing else could run). Now that it runs on a worker, the
  redirect is live for the GUI thread too, so anything it writes to stderr
  during a fit is discarded, most visibly the traceback PySide6 prints when a
  slot raises. Conversions run one at a time, so the redirects never nest.
  Kept as is on purpose: every alternative (a `warnings.catch_warnings`, a
  logging filter) is equally process-global, and a thread-aware stream proxy
  would mean replacing `sys.stderr` from library import. Note the consequence
  when debugging a GUI problem that only shows up during a fit.
* A conversion cannot be cancelled once started. The long call inside it
  (`VectorFitting.auto_fit`) is not interruptible, so a Stop button could not
  honour its own label. Superseding requests are coalesced instead, and the
  window stays usable meanwhile.
* The title bar's **View** switch is a row of exclusive buttons (`widgets.SegmentedSwitch`), one per view, rather than a drop-down: a drop-down keeps its other entries behind a popup, so nothing on the opening screen said the Plot view existed.
  `TopBar.set_view()` emits `view_changed` exactly as a click does, which is what carries the window along with the plot pop-out, dock, reset and simulation-import paths, and it stays silent when the requested view is already selected.
  A `&` in a segment label has to be doubled, since a button label reads it as a mnemonic marker and swallows it.
