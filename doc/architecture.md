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
   In universal mode it also keeps the band with the 0 Hz point still in it (`dc_net`, made passive by `io.passive_dc`), fitted itself when `state.fit_dc` asks for it and otherwise handed to passivity enforcement as one more refit to try.
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

`engine.convert` runs the whole conversion on one BLAS thread (`engine._one_blas_thread`, threadpoolctl 3.5 or newer, the first release that finds the scipy-openblas libraries of numpy 2 and scipy wheels). The matrices are small, and with the default 14 threads on a hybrid laptop CPU a 7-port core at order 24 with thermal noise converted in 905 s against 2.2 s on one thread. threadpoolctl changes the loaded libraries at run time and restores them afterwards, where environment variables would also reach every simulator snp2le starts. An explicit `OPENBLAS_NUM_THREADS` or `MKL_NUM_THREADS` turns the limit off, and so does a missing threadpoolctl. Conversions that overlap in threads share the limit through `process_state.ProcessSetting`: the first one in sets it and the last one out restores the count the process had. A save-and-restore per call left a program that ran 16 conversions in 8 threads on one BLAS thread for good, since the second conversion saved the first one's limit as the original. One thread gives the same result as an `OPENBLAS_NUM_THREADS=1` run of 0.1.11 in every record of the option-space dump. Against 0.1.11 at 14 threads the universal netlists of the bundled examples were unchanged at the 10 digits 0.1.12 printed, while a few wideband inductor fits settle elsewhere along their weakly determined values, the same kind of move another numpy or scipy makes.

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
* The wideband inductor fit (`structures/inductor_fit.py`) knows in advance how many
  least-squares runs it will make and reports after each one. It runs under its own
  plan, `engine._PLAN_STRUCTURE_WIDEBAND`, where the fit is 92 % of the weight, so the
  fractions of every other structure are unchanged.

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
CLI automatically. The registry order is the dropdown order. Structure mode opens on
`structures.default_structure(n_ports)`, the first entry with the file's port count that
is not a wideband fit, which keeps a slow fit from starting on its own. The three
inductors lead the dropdown, and a 3-port still opens on the in-phase Wilkinson.

A structure fitted over the whole band instead of read off at f_ext sets
`wideband = True`. The engine then calls its `extract()` with `progress` (a
`callback(fraction, message)` for the extract stage) and the fit options of
`inductor_wideband.wideband_options(state)` as keywords, skips the f_ext range note,
moves `metrics["messages"]` into `Results.messages`, and passes the IR to
`freq_traces()` and `default_plots()` so their views can follow the fitted port order.
The GUI shows its own page in place of f_ext (`TopBar.wide_page`), the Result panel shows
`metrics["f_fit_max"]` as *fitted up to*, and the CLI prints the fit band and
`metrics["segments"]` in place of f_ext.


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
* VACASK's builtin `mutual` takes k from 0 to 1 only, while the balun extracts a negative k. `netlist._vc_swapped_coils()` picks a terminal order per coupled coil that makes every k positive, which is the same circuit, and the VACASK header names the swapped coils. The Ngspice netlist keeps the negative k, which Ngspice accepts. The bundled VACASK testbenches declare `model mutual mutual` for the balun and the wideband inductors. The balun's VACASK response matches Ngspice's to 1.5e-7 in S.
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
  from a non-passive constant term) leaves the accurate fit in place instead. When perturbation fails, `_enforce_passivity_path()` tries a lower-order refit and, for a file with a 0 Hz point (`dc_net`), a refit at the same order that includes it, enforced the same way. Each counts only if it clears the ceiling and still fits the data (`_USABLE_RMS`), and the closer one wins. The refit's constant term is pinned to the DC point instead of free to run past 1, so it rescues fits whose violation is D: on the bundled examples with a DC point prepended, the balun and the 500 pH coil at order 6 go from near-passive to passive, and `tline_100um` at order 13 does too with scikit-rf 1.12 (not with 2.1.0). Without `dc_net` the branches and messages are those of 0.1.13. scikit-rf's `passivity_enforce` writes only the residues (1.12 and 2.1.0 alike), so the constant term D, the model's value at infinite frequency, is out of its reach. `universal.constant_term_sigma()` measures D, and a final model whose D is above its ceiling gets a message that names D and the knob that is left, another Max order. `Results.passivity_path` says which branch produced the model (`off`, `not needed`, `perturbed`, `reduced order` or `near-passive`, empty for a structure model), so a caller need not read it out of the messages. `universal._enforce_passivity()` keeps its three return values for callers outside snp2le, `_enforce_passivity_path()` adds the path. 1.0 is
  the floor because a lossless reciprocal network sits at exactly 1. An out-of-range
  number is clamped to the edge it overshot and a non-number falls back to the default
  (`universal.clamp_passivity_ceiling()`), so the GUI field answers "what is the limit"
  by showing it. The rule that the ceiling applies only while enforcing lives in
  `universal.effective_ceiling()` alone, so the GUI, the CLI and the engine cannot
  disagree about it.
* `ConverterState.max_order` is a model order, `n_real + 2 x n_complex`, and it reaches
  scikit-rf as `auto_fit(model_order_max=...)`. `Results.model_order` is that same count
  measured on the fitted poles, and it is the number of internal states in the netlist,
  since a conjugate pair costs `x_re` and `x_im`. `Results.n_poles` counts pole entries,
  where a conjugate pair is one, so it is the smaller of the two. The GUI and the CLI
  report the order with the pole count in brackets, because reporting only the pole count
  under the label `order` reads as the cap being exceeded. Below scikit-rf 1.12 `model_order_max` was only the exit
  test of the pole-growth loop and never applied to the initial pole set (3 real plus 3
  complex, order 9), so any cap under 9 was inert and a cap above it could be overshot by
  one batch of added pairs. `universal._auto_fit()` passes the initial counts 1.12 would
  compute itself, which fixes the first half on older versions and is inert on 1.12, and
  the second half is why the dependency floor is `scikit-rf>=1.12`.
* Resistor thermal noise is keyed on `ir.physical` (`netlist.py`): a universal
  macromodel's resistors are fit artifacts and are emitted with `noisy=0` in both
  dialects, while a structure model's resistors are real loss and keep their noise.
  The reasoning and the measured numbers are in the comment block above
  `netlist._NOISY_OFF`. `Element.noisy` overrides that per element (None follows
  `ir.physical`), and `netlist._silenced()` is the one place both renderers ask.
* `ConverterState.thermal_noise` (universal mode, off by default) appends the passive's
  thermal noise, kT(I - S S^H) at the ports, through `noise.add_thermal_noise()`, called
  by the engine after the model response and before the DC check, so the check covers it.
  `noise.state_space()` rebuilds the fit's real (A, B, C, D, E) from scikit-rf's public
  pole and residue attributes (the layout of its private `_get_ABCDE`), and
  `noise.spectral_factor()` solves the bounded-real Riccati equation with
  `scipy.linalg.solve_continuous_are` in time normalised to the largest pole, with V0
  the Cholesky factor of I - D D^T. The generator is N noisy 0.25 ohm resistors
  (`Element.noisy=True`) driving a copy of the state dynamics, injected into each port's
  sensor node `s_n` of the scikit-rf realisation at 2/sqrt(Z0) per unit of noise wave,
  and found by `noise._port_sensors()` from the 0 V source and reference resistor of
  each port. Each state is rescaled so the gains that drive it and the gains that read
  it meet in size, with a complex pair tied to one factor, because VACASK does not
  equilibrate its matrix (1.4 % off at low frequency without it). Before anything is
  added, V V^H is checked against I - S S^H on DC, the data band and four decades either
  side (`noise.CHECK_TOL`, 1e-6 kT). A model that is not strictly passive, has a
  proportional term or fails the check gets no generator, `Results.noise.ok` is False
  with the reason (naming D when min eig(I - D D^T) <= 0, since enforcement cannot fix that), the engine adds that reason to `messages`, the GUI refuses Export
  and the CLI writes nothing and exits non-zero. Any failed CLI conversion also removes the files an earlier run left at its output paths (`cli._remove_stale`), except those the same run wrote, so a Makefile cannot take a stale netlist for the result. Its notes go into `CircuitIR.notes`,
  which the renderers print in full after the provenance comments. `_PLAN_UNIVERSAL_NOISE`
  carries the extra stage, so the default plan's progress fractions are unchanged.
  `tests/test_noise.py` solves the emitted circuit with its own AC noise analysis and
  compares every port and correlation with Bosma's formula.
* The bundled `netlist/` examples are `bpf_ihp-sg13g2.s2p` at `--order 13`
  (`two_port`), `wpd_ihp-sg13g2.s3p` at `--order 13` (`three_port`) and
  `blc_ihp-sg13g2.s4p` at `--order 8` (`four_port`), exported with `--format both`.
  The rendered float tails depend on the BLAS the fit ran on, so a regeneration on
  another platform can differ in the last digits without anything being wrong. Since 0.1.13 every value is written at full precision (below), so a file regenerated on another platform differs in the last digits of many numbers.
* Element values are written as the shortest text that reads back as the same double (`netlist._num`, Python's `repr`). A universal realisation relies on cancellation between its controlled-source gains, and the 10 significant digits written up to 0.1.12 could break it: a synthetic 2-port (a 30 degree line, a 0.2 pF shunt and 5 ohm, 1 to 20 GHz) missed its own model by 2.2e-4 in S at order 20, 1.0 at order 24 and 6.7 at order 40, solved from the netlist text. VACASK's `acsp` on the same netlists read 9.5e-5, 0.27 and 1.3, and 4.4e-10, 7.1e-7 and 3.5e-6 at full precision. The bundled examples and real EM data were not affected (1.4e-8 at most). The text now reproduces the IR exactly, so the netlist is as close to the model as the realisation itself, 9.5e-6 at order 24 on that 2-port.
* A 0 Hz (DC) sample is dropped before a structure extraction, since it breaks the Y-/ABCD-parameter extraction and the MNA rebuild. A universal fit drops it by default as well and extrapolates to DC, which on the bundled `ind_d20` coil at order 13 gives a DC resistance of 1.29 ohm against the file's 1.096 ohm.
  `state.fit_dc` (GUI tick box *0 Hz* on the fit range caption, CLI `--fit-dc`) fits the band with the 0 Hz point instead. scikit-rf's `auto_fit` and `vector_fit` then enforce the DC point on the constant term (`enforce_dc=True`, their default), so the model meets it exactly, at a few times the in-band error. `io.passive_dc()` first clips singular values of S(0) above 1, since an EM solver's extrapolated DC point can come out a hair above passivity (the bundled line at 1.0001, ORCA files up to 1.0000036) and a fit pinned to it would inherit a negative DC conductance. Passivity enforcement can still move the DC point: scikit-rf preserves it only when no violation band starts at 0 Hz, and the engine reports a move in S above `engine._DC_MOVED` (1e-6).
  The tick box sits on the fit range's caption line with that line sized to nothing (`QSizePolicy.Ignored`), so the two fields set the box width and the bar keeps its 1899 px in the container (1920 px screen) and 1735 px on Windows. Its indicator is 12 px to fit the caption line's height: at 10 px the Windows 11 style draws a circle without a check mark.
* The transmission-line ladder uses 2 L-cells by default (`N_SEGMENTS` in
  `snp2le/core/structures/tline.py`) and can be set from 1 to 10 stages.
* `inductor-wideband` and `inductor-ct` port Volker Muehlhaus' inductor_fit
  ([lumpedmodel](https://github.com/VolkerMuehlhaus/lumpedmodel), used under Apache-2.0
  with his permission). `structures/inductor_fit.py` is the fit: analytic seeds from the
  pi (2-port) or delta (3-port) decomposition, then `scipy.optimize.least_squares` on
  log10 of the element values over the data up to 1.2 x the self-resonance frequency,
  from the seed plus two perturbed starts with a fixed random seed, so a fit is
  reproducible for one set of numpy, scipy and BLAS. Another set can settle elsewhere along
  directions the data barely constrains: in IIC-OSIC-TOOLS (numpy 2.5, scipy 1.18) the
  bundled center-tapped fit has L_s,h and k 4.5 % and R_skin2 2.3 x away from Windows
  (numpy 2.4, scipy 1.17), at a 0.2 % lower cost, while L, Q, the SRF and the
  well-determined elements agree within 0.3 %. The skin section whose corner lies above the
  band and the split between L_s,h and k are those directions.
  By default the fit chooses 1 to 3 coil segments (the fewest within 10 % of the best
  cost), decides port and half-coil symmetry from the data (5 % threshold), and keeps a
  2-port substrate coupling only if it improves the cost by more than 10 % and passes a
  plausibility check. `structures/inductor_wideband.py` turns the totals into one set of
  elements per segment, with the substrate network distributed over the coil nodes, and
  couples every half-1 cell to every half-2 cell with k/segments, which is the fit's
  M/segments^2 per cell pair. The rebuilt response matches the fit's own model function to
  1e-9 in S (`tests/test_inductor_wideband.py`). A value the fit puts below the netlist's floor is raised to it (`netlist._LIMITS`, 1 aF for a capacitor), which moves the netlist off the fit: the basic fit of `ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p` ends at its C_s bound of 0.1 aF, and the 1 aF in the netlist moves S by 2.1e-4, well inside the fit's own error. Its k is the effective coupling
  including the center tap lead inductance, which terminal data cannot separate from M.
  A full fit takes 2 s (2-port) to 6 s (center tap) on the bundled examples, the basic
  model under 1 s. The coupled half coils are stamped entry by entry (`inductor_fit._stamp_coupled`), in the summation order of the einsum over every node and branch pair it replaced, so the bits are the same while a 10-segment center-tap fit went from 605 s to 37 s on one machine. The dense SRF grid is evaluated in chunks of 2000 frequencies (`_on_grid`), which took that fit's peak memory from 1.9 GB to 0.34 GB. A values table longer than 12 rows is shown in two columns
  (`design_view._ONE_COLUMN_ROWS`).
* inductor_fit's options are all ported: a fixed segment count (`coil_segments`, 1 to 10),
  a fixed substrate variant (`substrate`), the peak-Q weight A and the shunt accuracy K
  (`peak_q_weight`, `shunt_accuracy`, defaults 2 and 0.01), and the center tap port
  (`center_tap`). 0 and "auto" in `ConverterState` leave the choice to the fit, and
  `inductor_fit.check_options()` is the one place that refuses an impossible set (basic
  with more than 1 segment, basic or the 3-port with substrate coupling), which the CLI
  calls before it reads a file and the engine reaches through the fit. The center tap
  defaults to the port the low-frequency data puts in the middle of the coil: with the
  other two ports grounded, current from a coil end mostly leaves through the nearby
  center tap, so the two coil ends share the weakest transfer admittance
  (`inductor_fit._center_tap_hint`). The fit reorders the data to (end, end, tap), and the
  IR keeps the file's port order, so the pins match the EM ports. A deliberately wrong
  port still fits and says which port the data points at. The GUI page offers *Basic
  model*, *Segments* 1 to 3 (*Center tap* for the 3-port), and the two weights as tick
  boxes at their defaults. The substrate variant, other weights and more segments are CLI
  only, and the GUI always sends the values its controls show, so a hand-edited design
  cannot carry a hidden option into a GUI conversion.
* `fit_universal` points `sys.stdout` and `sys.stderr` at throwaway buffers during the fit (`universal._QUIET`), since scikit-rf reports through warnings, which Python writes to `sys.stderr`. The streams belong to the whole process, not to one thread, so while the GUI's worker fits, anything the GUI thread writes to them is discarded too, most visibly the traceback PySide6 prints when a slot raises. Note that when debugging a GUI problem that only shows up during a fit. Every alternative (a `warnings.catch_warnings`, a logging filter) is just as process-wide, and a thread-aware stream proxy would mean replacing `sys.stderr` from library import.
  A library caller can run conversions in parallel threads, and a save-and-restore per call then breaks: the second fit saves the first one's buffer as the original and puts it back last, so the program never prints again. `process_state.ProcessSetting` holds the redirect from the first fit in to the last one out instead. `warnings.catch_warnings` and a raised logger level save and restore the same way, so swapping the redirect for them would only move the problem: in a test with 16 conversions in 8 threads they left the warning filters and the scikit-rf log level changed for good.
* scikit-rf's `auto_fit` can cycle for good. Its adding and skimming loop has no pass limit, its accuracy exit compares a peak error that is never updated inside the loop, and a pass can skim what it adds, so on some EM data it alternates between two pole sets (6 of 3,200 ORCA fits at `model_order_max=20`, scikit-rf issue 1452). `universal._RelocationLimit` counts the pole relocations of the one fit, as a wrapper on the instance so that parallel fits keep their own counts, and stops it past `_AUTO_FIT_MAX_RELOCATIONS` (250, converging fits need 8 to 120 and the bundled examples at most 26). `_refit_stuck()` then redoes the fit with `vector_fit` at the pole counts it had reached, and the messages say so. Another cap is no cure, since one of those files cycles at 20, 21 and 22.
* A conversion cannot be cancelled once started. The long call inside it
  (`VectorFitting.auto_fit`) is not interruptible, so a Stop button could not
  honour its own label. Superseding requests are coalesced instead, and the
  window stays usable meanwhile.
* The title bar's **View** switch is a row of exclusive buttons (`widgets.SegmentedSwitch`), one per view, rather than a drop-down: a drop-down keeps its other entries behind a popup, so nothing on the opening screen said the Plot view existed.
  `TopBar.set_view()` emits `view_changed` exactly as a click does, which is what carries the window along with the plot pop-out, dock, reset and simulation-import paths, and it stays silent when the requested view is already selected.
  A `&` in a segment label has to be doubled, since a button label reads it as a mnemonic marker and swallows it.
