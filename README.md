<p align="center">
  <img src="https://raw.githubusercontent.com/iic-jku/snp2le/main/snp2le/gui/assets/snp2le_logo.svg" alt="snp2le logo" width="140">
</p>

# snp2le: A PySide6 Interactive GUI and CLI-based S-Parameter to Lumped-Element Netlist Converter

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/iic-jku/snp2le/blob/main/LICENSE)
[![License Check](https://github.com/iic-jku/snp2le/actions/workflows/license-check.yml/badge.svg)](https://github.com/iic-jku/snp2le/actions/workflows/license-check.yml)
![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)
![GUI: PySide6-Essentials](https://img.shields.io/badge/GUI-PySide6--Essentials-41CD52.svg?logo=qt&logoColor=white)
[![PyPI](https://img.shields.io/pypi/v/snp2le.svg)](https://pypi.org/project/snp2le/)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21189545.svg)](https://doi.org/10.5281/zenodo.21189545)

(c) 2026 Simon Dorrer

Institute for Integrated Circuits and Quantum Computing (IICQC), Johannes Kepler University (JKU), Linz, Austria

> [!IMPORTANT]
> The converter (GUI and CLI) runs anywhere with **Python ≥ 3.10**, see [Install](https://github.com/iic-jku/snp2le#install) below.
> *Running* the exported netlists in a testbench additionally needs **Xschem** plus **Ngspice** and/or **VACASK**. The easiest way to get all of them is the [IIC-OSIC-TOOLS](https://github.com/iic-jku/IIC-OSIC-TOOLS) container. Since tag `2026.07`, `snp2le` has been installed directly in the [IIC-OSIC-TOOLS](https://github.com/iic-jku/IIC-OSIC-TOOLS) container.



## Description

**snp2le** turns a Touchstone **`.sNp`** S-parameter file (for example from an [AWS Palace](https://awslabs.github.io/palace/) EM simulation) into an equivalent **lumped-element netlist** for **Ngspice** (Berkeley SPICE3) and **VACASK** (Spectre syntax). An EM-extracted structure can then be co-simulated at circuit level, without re-running the field solve.

It offers two conversion philosophies:

- **Universal (any N-port).** Vector-fits the S-parameters with [scikit-rf](https://scikit-rf.org) `VectorFitting`, optionally enforces passivity, and synthesises a passive macromodel of R, C and controlled sources. It works for any structure and port count, and is electrically exact but not physically interpretable. Its resistors are emitted noiseless (`noisy=0`, understood by both Ngspice and VACASK): they exist to reproduce the fitted response, not to model a device, and charging thermal noise against them would report noise that tracks the fit order instead of the structure. So by default the model is noiseless (ideal), and the **Thermal noise** option adds the noise the lossy passive really has, kT(I - S S<sup>H</sup>) at its ports, as a generator computed from the fit. See [Thermal noise](https://github.com/iic-jku/snp2le#thermal-noise).
- **Structure-specific.** Fits a known physical topology, so every component maps to reality (series L, shunt C, coupling k, and so on) at a chosen **extraction frequency**. The two wideband inductor models are the exception: they are fitted over the whole band, up to past the self-resonance, and also handle a center-tapped coil. Its resistors model real loss (a Wilkinson's isolation resistor, a coil's conductor loss), so they keep their thermal noise. See [Available structures](https://github.com/iic-jku/snp2le#available-structures).

Either mode fits the file's full frequency range by default, or a **fit range** of your choosing (e.g. only 110 GHz to 170 GHz of an 80 GHz to 240 GHz EM sweep), so the model order is spent on the band the block actually operates in.

A single dialect-agnostic **Circuit IR** drives both netlist backends and the on-screen schematic, so the outputs always agree. The code is split into a pure-Python, Qt-free `snp2le.core` (fully unit-tested) and a thin `snp2le.gui` on PySide6-Essentials, both driven by one entry point, `engine.convert(state, net)`.

A fit of a large N-port runs for seconds to minutes, so it runs on a worker thread and reports as it goes: the GUI shows what the fit is doing, how long it has been running and a progress bar, then leaves the outcome on screen when it finishes, and the CLI draws the same progress on a terminal. See [Watching a conversion](https://github.com/iic-jku/snp2le#watching-a-conversion).

<p align="center">
  <a href="https://raw.githubusercontent.com/iic-jku/snp2le/main/doc/fig/snp2le_gui_bpf.png"><img src="https://raw.githubusercontent.com/iic-jku/snp2le/main/doc/fig/snp2le_gui_bpf.png" alt="snp2le GUI, band-pass filter" width="85%"></a><br>
  <em>The snp2le GUI converting a band-pass filter (BPF) S-parameter file into a lumped-element netlist.</em>
</p>

<p align="center">
  <a href="https://raw.githubusercontent.com/iic-jku/snp2le/main/doc/fig/snp2le_plots_bpf.png"><img src="https://raw.githubusercontent.com/iic-jku/snp2le/main/doc/fig/snp2le_plots_bpf.png" alt="snp2le plots, data vs model vs simulation" width="85%"></a><br>
  <em>Plot view: loaded data (grey) vs extracted model (blue) vs imported testbench simulation (red).</em>
</p>


## Directory Structure

```text
📁 snp2le/
├─ 📁 doc/                    architecture notes and screenshots
│  ├─ 📁 fig/                 GUI and plot screenshots
│  └─ architecture.md         data flow, internals, how to extend
├─ 📁 netlist/                exported lumped-element netlists
│  ├─ 📁 spectre/             VACASK (.inc) + syntax_cheatsheet.inc
│  └─ 📁 spice/               Ngspice (.spice)
├─ 📁 schematic/
│  └─ 📁 xschem/              DUT symbols (*.sym) and xschemrc
├─ 📁 snp2le/                 the application package (pip-installable)
│  ├─ 📁 core/                pure Python, Qt-free, all the maths
│  │  ├─ 📁 structures/       physical extractors, one per topology
│  │  │  ├─ __init__.py       registry (GUI dropdown + CLI find it)
│  │  │  ├─ base.py
│  │  │  ├─ balun.py
│  │  │  ├─ branchline.py
│  │  │  ├─ inductor_fit.py   wideband inductor fit (2-port and center tap)
│  │  │  ├─ inductor_pi.py
│  │  │  ├─ inductor_wideband.py
│  │  │  ├─ mim_cap.py
│  │  │  ├─ tline.py
│  │  │  └─ wilkinson.py
│  │  ├─ __init__.py
│  │  ├─ dc.py                DC operating-point (singularity) check
│  │  ├─ dcpin.py             DC pin: a universal model meets the file's 0 Hz point
│  │  ├─ engine.py            convert(state, net) -> Results, the entry point
│  │  ├─ io.py                load Touchstone, parse Ngspice tables
│  │  ├─ ir.py                dialect-agnostic Circuit IR
│  │  ├─ mna.py               rebuild N-port S-parameters from an RLC IR
│  │  ├─ netlist.py           render the IR to Ngspice and VACASK
│  │  ├─ noise.py             thermal-noise generator of a universal model
│  │  ├─ process_state.py     process-wide settings shared by parallel conversions
│  │  ├─ progress.py          progress reporting for long conversions
│  │  ├─ state.py             ConverterState and Results dataclasses
│  │  ├─ units.py             engineering-notation parse and format
│  │  ├─ universal.py         vector-fit passive macromodel
│  │  └─ xschem.py            headless Xschem netlist and simulate
│  ├─ 📁 examples/            Touchstone .sNp samples (BPF, ind, balun, ...)
│  ├─ 📁 gui/                 PySide6-Essentials, no maths
│  │  ├─ 📁 assets/           logos (svg and png), snp2le.ico, spin-box arrows
│  │  ├─ __init__.py
│  │  ├─ design_view.py       results, values, tolerances, schematic
│  │  ├─ fit_runner.py        runs engine.convert on a worker thread
│  │  ├─ fit_status.py        the conversion progress / outcome indicator
│  │  ├─ main_window.py       the controller
│  │  ├─ plot_view.py         four S-parameter / extracted-param plots
│  │  ├─ top_bar.py           load, mode, structure, options, run
│  │  └─ ...                  help_dialog.py, style.py, widgets.py, and more
│  ├─ __init__.py             package version
│  ├─ __main__.py             single entry point (GUI, GUI on a file, or -b for the CLI)
│  ├─ app.py                  the GUI launcher (__main__ starts it)
│  └─ cli.py                  the batch CLI behind -b
├─ 📁 testbenches/
│  └─ 📁 xschem/              N-port testbenches (Ngspice and VACASK)
│     ├─ 📁 plot_simulations/ plot scripts (plot_*.py, sparam_plot.py, ngspice2python.py)
│     │  ├─ 📁 data/          simulation result tables, overlaid on the plots
│     │  └─ 📁 figures/       PNG figures written by the plot scripts
│     └─ 📁 simulations/      generated netlists and raw output (not tracked)
├─ 📁 tests/                  pytest suite
│  ├─ test_blas_threads.py    a conversion runs on one BLAS thread
│  ├─ test_core.py
│  ├─ test_dc_point.py        the 0 Hz point of a universal fit (no Qt)
│  ├─ test_gui_fit_progress.py  headless non-blocking-conversion regressions
│  ├─ test_gui_fit_range.py   headless fit-range control
│  ├─ test_gui_launch_file.py  headless GUI opened on a command-line file
│  ├─ test_gui_order_readout.py  headless order line in the Result panel
│  ├─ test_gui_passivity_ceiling.py  headless passivity-ceiling control
│  ├─ test_gui_plot_view.py   headless Plot view curves (tuple or list item data)
│  ├─ test_gui_sim_flow.py    headless GUI run/poll/import regressions
│  ├─ test_gui_thermal_noise.py  headless Thermal noise control
│  ├─ test_gui_top_bar_layout.py  headless control-strip layout invariants
│  ├─ test_gui_view_switch.py  headless View switch (both views on screen)
│  ├─ test_gui_wideband_inductor.py  headless wideband inductor page
│  ├─ test_inductor_wideband.py  the wideband inductor fit, netlist and noise
│  ├─ test_main_dispatch.py   the entry point's argument dispatch (no Qt)
│  ├─ test_noise.py           the thermal-noise generator against Bosma's formula
│  ├─ test_parallel_callers.py  fits in parallel threads give the streams back
│  ├─ test_progress.py        progress reporting and the fit watcher
│  ├─ test_qt_essentials.py   guards the Essentials-only dependency
│  ├─ test_reproducibility.py same input, same model, across processes
│  └─ test_xschem.py
├─ 📁 LICENSES/               license texts the REUSE check resolves against
│  └─ Apache-2.0.txt
├─ 📁 .github/workflows/      CI
│  └─ license-check.yml       reuse lint: every file carries copyright + license
├─ CITATION.cff
├─ LICENSE                    Apache-2.0
├─ MANIFEST.in                sdist manifest (bundles examples and assets)
├─ pyproject.toml             packaging, dependencies, snp2le entry point
├─ README.md
├─ REUSE.toml                 licensing of files that cannot carry an SPDX header
└─ requirements.txt           runtime dependencies (mirrors pyproject.toml)
```


## How to Use

### Install

From PyPI:

```bash
pip install snp2le
# or, for an isolated install with its own command on PATH:
pipx install snp2le
```

From source (for development), an editable install with the `dev` extra pulls in the runtime dependencies plus pytest, build, twine and reuse:

```bash
git clone https://github.com/iic-jku/snp2le.git
cd snp2le

python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate

pip install -e ".[dev]"
```

### Run the GUI

```bash
snp2le              # after installing (pip / pipx)
snp2le design.s4p   # the same, opened on that Touchstone file
python -m snp2le    # from the repo root of a source checkout, without installing snp2le itself
```

A bundled example is preloaded when no file is named. More live in `snp2le/examples/`.

Naming a `.sNp` file on the command line opens the GUI on it instead of the example, with the port count, the fit range and the first conversion taken from that file. This is how a tool that just wrote the file hands it over, for example the *Model Fit* button of [setupEM](https://github.com/VolkerMuehlhaus/setupEM) after an AWS Palace run. *Reset* returns to that file rather than to the example. A file that cannot be read is reported in a dialog (and on stderr) and the example is loaded in its place, so the window opens either way.

> [!NOTE]
> Start it as a module (`python -m snp2le`), not `python snp2le/app.py`. The launcher imports the `snp2le` package, which Python only finds when it is run as a module from the repo root (or after `pip install`).

### Typical workflow

1. **Load** a Touchstone `.sNp` file from the top bar, or name it on the command line (`snp2le design.s4p`, see above). The header shows the port count and frequency range. A file whose ports do not share one real reference impedance (one per port, complex, or varying with frequency) is renormalised to 50 ohm before the conversion. The model describes the same device, the plots and the RMS error refer to 50 ohm, and the message line of the Conversion panel (the CLI's `note:` line) says so. A Touchstone 1.1 option line with one reference resistance per port (`# GHz S RI R 50 75`) needs scikit-rf 2.2 or later and is refused on older versions, which read only its first value.
2. **Choose a mode.** Universal (set *Max order*, *Enforce passivity* and the *Passivity ceiling* it works towards, and tick *Thermal noise* for a model that carries the passive's noise) or Structure-specific (pick a structure and set the *extraction frequency*). Some structures expose an extra option such as *Stages*, *Isolation R* or *Resistive loss*. The wideband inductors have no extraction frequency and show their own options instead: *Basic model*, *Segments* (*Center tap* for the center-tapped one), *Peak-Q weight* and *Measured data*. *Max order* bounds the model order, `n_real + 2 x n_complex`, which is the number of internal states per port in the netlist (an N-port has N times that). The *Result* panel's *order* line reports the order the fit settled on and, in brackets, its pole count, where a complex-conjugate pair counts once, so the two numbers differ by design.
3. **Restrict the fit range** (optional, both modes). The *Fit range (GHz)* fields start at the loaded file's own span, so they always name the band being fitted. Enter two plain numbers in GHz (e.g. `110` and `170`) to fit only a sub-band. The *Result* panel shows the band actually fitted, and the RMS error, the tolerances, the plots and a testbench run's sweep all follow it. An edge outside the data is clamped to the data and reported, an empty or inverted band is refused. The **DC pin** tick box on the caption line (universal mode, ticked by default) makes the model meet a file's 0 Hz sample, see [The 0 Hz point](https://github.com/iic-jku/snp2le#the-0-hz-point).
4. **Inspect** the result, element values, per-element **tolerances** at the extraction frequency, the drawn schematic, and the generated netlist in the **Design & Schematic** view.
5. **Compare** the loaded data (grey) against the extracted model (blue) in the **Plot** view (up to four traces, magnitude and phase). The **View** switch at the right of the title bar carries both views side by side and fills the one you are on, so a click moves between them.
6. **Export** the netlist. *Export Ngspice* writes a `.spice` file and *Export VACASK* writes an `.inc` file. The `.SUBCKT` is named after the file, so a testbench that instantiates it resolves the include. The header names the snp2le version that wrote the netlist.

> [!TIP]
> The **Help** button in the top bar opens a full in-app guide to every control.

### Passivity and the passivity ceiling

A macromodel is **passive** when the largest singular value of its S-matrix, sigma_max, stays at or below 1 at every frequency. That is the same statement as "it can never deliver more power than it absorbs". A non-passive model is not merely inaccurate: a transient run can feed on the excess energy and grow without bound, so the simulation diverges or refuses to converge even though its AC response looked fine.

Making a model passive is not free. A vector fit typically violates passivity *outside* the band it was fitted to, and pushing it back below 1 there costs accuracy inside the band. On the bundled `bpf_ihp-sg13g2.s2p` at order 13, the raw fit reaches sigma_max = 1.016 with an RMS error of 2.9e-5, and enforcing passivity takes it to 1.000 at 1.5e-3, which is 50x worse.

The **Passivity ceiling** is how far the enforcement has to go. It is the sigma_max the perturbation works towards, so it buys accuracy back in exchange for a bounded, known violation:

- **Enforce passivity ticked** (the default): the fit is perturbed until it reaches the ceiling. At `1.00` that is strict passivity, exactly what the tool did before the field existed. Raise it to stop short.
- **Unticked**: nothing is enforced and the raw fit is exported as it is. The ceiling field greys out at `1.00`, since nothing is aiming at it, and sigma_max is still measured and reported so you can see what you are shipping.

A ceiling above what the fit already measures leaves the model untouched rather than *adding* gain to reach it. On `wpd_ihp-sg13g2.s3p` at order 6, where the raw fit sits at 1.083:

| Target | resulting sigma_max | RMS error | vs. the raw fit |
| --- | --- | --- | --- |
| not enforced | 1.0826 | 8.7e-04 | the fit itself |
| `1.00` (strict) | 0.9999 | 2.6e-03 | 2.9x worse |
| `1.05` | 1.0499 | 1.3e-03 | 1.5x worse |
| `1.15` | 1.0826 | 8.7e-04 | untouched, already below |

Reasonable ceilings:

| Target | When |
| --- | --- |
| `1.00` | transient or long harmonic-balance runs, and anything handed to a colleague |
| `1.01` to `1.05` | AC or S-parameter sweeps, where a per-cent violation outside your band cannot do anything |
| up to `1.20` | as a diagnostic while you look at what the fit is doing |

Why those two limits, and what an out-of-range entry does:

- **`1.00` is the floor** because it is the physical criterion itself. A lossless reciprocal structure, an ideal coupler or a lossless line, has sigma_max exactly 1, so a floor below 1 would reject networks that are perfect.
- **`1.20` is the ceiling** because past roughly 20 % of voltage gain (1.44x in power, +1.6 dB) at the worst frequency there is enough excess energy to grow a transient run without bound. It is also well clear of the bundled examples: at orders 6 and 13 their raw fits stay at or below 1.02, the WPD at order 6 reaches 1.08, and a broken fit jumps to 2.18 or 5.24.
- **A number outside the range is replaced by the limit it overshot.** Type `9.9` and the field shows `1.20`, type `0.5` and it shows `1.00`. That is deliberate: the field teaches you the limits without anyone reading this paragraph first. Text that is not a number at all has no limit to snap to, so it falls back to `1.00`. The CLI is stricter and refuses the run outright rather than substituting, since a batch script silently getting a different ceiling than it asked for is worse than a visible error.

**A ceiling is not always reachable.** The perturbation only moves the model's residues, so a violation band that runs to infinity, caused by a non-passive constant term, cannot be corrected at any ceiling. The bundled `tline_100um_ihp-sg13g2.s2p` at order 13 is one: its constant term sits at 5.24. A file that carries a 0 Hz point, as this one does, then also gets a refit that includes it, which scikit-rf meets through the constant term, so the refit lands on another model and is kept if it clears the ceiling and fits closer than a lower-order refit. The line at order 13 comes out passive that way, at model order 9 and an RMS error of 1.5e-3, with scikit-rf 1.12, 2.1.0 and 2.2.0 alike. That outcome is fragile, though: changing every S value of the file by a random 1e-12 made the refit miss in 1 to 6 of 8 tries (order 9 and 13 alike, depending on the draw and the platform's numerics), and the line then reads near-passive at 5.24. Order 6 gave the same result in all 8. Like the lower-order refit, a passing refit replaces the accurate near-passive fit even at a larger error (the 500 pH coil with a 0 Hz point added, at order 6: 7.0e-5 becomes 3.7e-2), and with **Thermal noise** ticked a strictly passive candidate wins over one that only meets a raised ceiling, since only it can carry the noise. The refit needs a fit range that starts at the file's first sample above 0 Hz. When nothing reaches the ceiling, the accurate fit is kept rather than a wrecked one, and the result reads *near-passive*. The fix is a lower **Max order**, not a higher ceiling, since order 6 brings the same file to 0.9997 by plain perturbation. Whenever the constant term D, the model's value at infinite frequency, is above the ceiling, the message line says so with its sigma, so this case cannot be mistaken for a violation inside your band.

The **Result** panel reports the measured sigma_max next to the ceiling it was judged against, green inside the ceiling and red outside it, so a raised ceiling never reads as a clean pass without the number that earned it. When there is a violation, the message line under the panel (and the CLI's `note:` line) names the frequency of the peak. Read it before you decide what to do:

- **At 0 Hz or inside your band**: a real hazard for a transient run or a DC operating point. Enforce, or raise the order. An AC or S-parameter sweep of a band far above 0 Hz does not see a peak at 0 Hz, which is why the raised-ceiling examples above can accept one.
- **Far above the top data point**, at 10^4 times it or so: that is the model's high-frequency asymptote, not a resonance. It usually means the fit order is too high for the file. The bundled `tline_100um_ihp-sg13g2.s2p` without enforcement reaches sigma_max = 5.24 at order 13, at 10^4 times its top data point, and only 1.018 at order 6.

### The 0 Hz point

Some files carry a 0 Hz sample, an EM solver's DC point. The bundled `ind_d20_w7_sp3_nw1_r10_ihp-sg13g2.s2p` and `tline_100um_ihp-sg13g2.s2p` do. A vector fit drops it and extrapolates to DC from the samples above it, and a coil's DC resistance sits in a small departure of S21 from 1 (0.3 % for 0.3 ohm between two 50 ohm ports), so a fit error of 1e-3 in S moves it by tens of percent. On the bundled coil at order 13 the fit reads 1.29 ohm against the file's 1.096 ohm. On 20 ORCA EM inductors at order 20 the fit is 20 % off in the median and 157 % at worst. A coil in a bias or supply path then drops the wrong voltage.

**DC pin** (the tick box on the *Fit range* caption line, CLI `--dc-pin`, on by default) makes the model meet the file's 0 Hz point:

- It leaves the fit as it is and adds the difference at DC through a first-order low-pass: Y = Y<sub>fit</sub> + ΔY / (1 + s/ω<sub>c</sub>), with ΔY = Y<sub>dc</sub> - Y<sub>fit</sub>(0) and a corner of 160 Hz (CLI `--dc-pin-fc`). Per port a controlled source copies the port voltage, scaled by 1e-6, onto a node loaded by 1 ohm and 1 mF, and one controlled source per nonzero entry of ΔY feeds the correction back into the port. The scaling changes nothing in the response, it keeps VACASK, which does not scale its matrix, as exact as Ngspice (1e-15 against 4e-7 at 1 THz without it). The elements are `Gdcp_*`, `Rdcp_*` and `Cdcp_*`, and the resistors are noiseless.
- At DC the model then is the file: the coil reads 1.0964 ohm at every order, in Ngspice and VACASK alike, and the ORCA inductors land on their 0 Hz point to 1e-11 in the median. Above the corner the correction fades as fc/f, and the pin never moves the fitted band by more than the fit's own RMS error: by 8e-9 on the coil at order 13, by at most 7e-7 on the ORCA files at order 20 and by 7e-6 in the median (1.8e-4 at most) at order 6, their lowest sample above 0 Hz being 10 MHz.
- The 0 Hz point is taken real and symmetric, and its singular values are clipped to 1 - 1e-6, since an EM solver's extrapolation can put them a hair above 1 (the bundled line at 1.0001, ORCA files up to 1.0000173) and a mode at exactly 1 is not strictly passive. That is what the pinned model meets, so the ORCA file at 1.0000173 reads 2e-6 off the unclipped point, and a mode without a DC path keeps 1e-8 S (100 Mohm). The note says when the point was clipped or had to be made real and symmetric.
- The pin is checked before it is kept. It is skipped, with a note saying why, if it would take a frequency where the fit is passive to sigma_max 1 or above (checked from 0.16 Hz up through the band), move the fitted band by more than the fit's own RMS error, or make the DC operating point singular. The last happens when the fit nearly shorts a port at DC, so that the correction would have to cancel a large conductance. A file whose 0 Hz point shorts a port is named as such, since no finite conductance meets it. The passivity result and the thermal-noise generator stay those of the fit.
- It acts in universal mode on a file with a finite 0 Hz sample, also when the fit range starts above it. A file without one sees no change, and the CLI warns when a pin option was given for it. Structure modes drop the 0 Hz point, since their extraction divides by the frequency, and the wideband inductors fit their DC resistance themselves.
- `--dc-island-leak S` gives each DC mode without a path to ground (the common mode of a series coil, both terminals of a capacitor) that conductance, which can help a harmonic-balance run converge. It is 0 by default, so the model keeps the file's DC behaviour, apart from the 1e-8 S of the clip.
- The corner and the island leak have no control in the window, but a design file saved with *Save design* carries them, and one written by hand or a script can set them. A value that differs from the default, from the CLI or from a loaded design, is named at the end of the pin's note, for example `Non-default settings: corner 1 kHz (default 160 Hz)`, which the GUI shows in the message line of the Conversion panel. *Reset* returns both to the defaults. In a design file, `null` means the default, and a value that is no number (`true`, a string) refuses the design, since `true` would read as 1. A number out of range, NaN included, loads and skips the pin with a note.

What it costs, below the corner the model is the pin's rather than the fit's:

- In a transient run a bias step reaches its DC value on the time scale 1/(2π fc), 1 ms at 160 Hz. The circuit around the model sets the exact value: the bundled coil between two 50 ohm ports settles with 0.85 ms. A higher `--dc-pin-fc` settles faster and moves the band more.
- The thermal-noise generator carries the fit's loss, so below a few kHz the noise is that of the fit's DC conductance, not the file's.

Untick **DC pin** (CLI `--no-dc-pin`) to leave the DC point to the fit. The refit in passivity enforcement (above) uses the 0 Hz point on its own, whichever way the box is set, clipped the same way, since a coil's open common mode sits at exactly 1 there and a refit that met it could not carry thermal noise.

### Thermal noise

A lossy passive at temperature T is a noise source, and its noise follows from its S-parameters alone: the noise waves leaving its ports have the correlation kT(I - S S<sup>H</sup>) per hertz (Bosma's theorem, Nyquist's for an N-port). A lossless block adds no noise, and a block with loss adds the noise of that loss, correlations between its ports included.

A universal model cannot take that noise from its own resistors, which place the fit's poles rather than model the structure's loss and are therefore emitted with `noisy=0`. By default it is noiseless, an ideal block. Tick **Thermal noise** (CLI: `--thermal-noise`) to add the noise the passive really has:

- snp2le computes a noise generator from the fitted model itself, the spectral factor of I - S S<sup>H</sup> given by the bounded-real lemma, and appends it to the subcircuit.
- N resistors of 0.25 ohm, one per port, are its only noise sources (`Rnz_e1` to `Rnz_eN`), since 4kTR = kT is the noise power a matched port emits. They drive a copy of the model's state dynamics (`Cnz_x*` and controlled sources `Gnz_*`), which injects the noise waves into each port's internal sensor node.
- Nothing feeds back into the fitted network, so its S-parameters and its DC operating point stay what they are without the option. The option only steers passivity enforcement at a raised ceiling, where a strictly passive candidate then wins (see [Passivity and the passivity ceiling](https://github.com/iic-jku/snp2le#passivity-and-the-passivity-ceiling)).
- The noise follows the simulator temperature like any resistor's, while the S-parameters do not change with it.
- In a noise analysis the block's share is the sum of its `Rnz_e*` entries. Both dialects carry the generator, the simulators differ in which analyses see it. VACASK sees it in `noise`, `hbnoise`, `pnoise` and transient noise (`noisemode="sde"`). Ngspice sees it in `.noise` only, since it has no periodic noise analysis and adds no resistor noise to a transient run, so a mixer's noise figure through a fitted passive is a VACASK job.
- The netlist grows by about 2N + 3 lines per state, where a model has N times its model order states: the bundled WPD at order 6 (fitted at model order 4, 12 states) gains 113 lines, a 7-port at order 23 goes from 1892 to 4659.

The *Result* panel's *noise* row says what the netlist carries: *noiseless*, *thermal (R) ✓* in green once the generator is added, *NOT added* in red when it cannot be, and *thermal (R)* for a structure model with resistors, which carry their own noise.

**It needs a strictly passive model.** The generator exists only where sigma_max stays below 1 at every frequency, far outside the data included, so keep *Enforce passivity* ticked at a ceiling of `1.00`. When the model still is not strictly passive (a raised ceiling, enforcement off, or a fit enforcement cannot fix), no noise is added and the message names the model's sigma_max. When the cause is the constant term D, which enforcement cannot change, the message names D, and another **Max order** is the knob that is left. The GUI still shows the model and its plots, its Result panel reads *NOT added*, and Export refuses. The CLI writes no file, removes one an earlier run left at that path, and exits non-zero. A noiseless netlist under a name you asked to be noisy would otherwise enter a noise budget unnoticed.

Every generator is checked before it is added: V V<sup>H</sup> = I - S S<sup>H</sup> over DC, the data band and four decades either side, within 1e-6 kT (the bundled examples land between 1e-15 and 1e-13). Simulated, with every port terminated in noiseless 50 ohm, the port noise must be Z<sub>0</sub> kT(I - S S<sup>H</sup>):

| Model | Ports, states | Ngspice `noise` | VACASK `noise` |
| --- | --- | --- | --- |
| `bpf_ihp-sg13g2.s2p`, order 13 | 2, 26 | 3.6e-7 | 9.7e-7 |
| `wpd_ihp-sg13g2.s3p`, order 6 | 3, 12 | 3.5e-7 | 9.4e-7 |
| `blc_ihp-sg13g2.s4p`, order 6 | 4, 24 | 3.5e-7 | 9.4e-7 |
| a 7-port receiver core, order 23 | 7, 161 | 3.6e-7 | 9.4e-7 |

The numbers are the largest relative deviation from 1 GHz to 10 THz, on every port and on the difference of ports 1 and 2, which tests the correlation. Both are constant offsets set by each simulator's physical constants, the same a plain resistor shows. VACASK transient noise (`noisemode="sde"`) through the WPD generator matches VACASK's own `noise` analysis within 3.4 % over 5 GHz to 2 THz, and plain resistor noise through the same fitted model within 2.5 %, both the scatter of a single 40 ns record. `tests/test_noise.py` keeps the netlist honest without a simulator: it solves the emitted circuit with its own AC noise analysis and checks every port and every correlation against the same formula.

How much the noise matters depends on where the passive sits. In front of the first gain stage it adds roughly its loss in dB to the noise figure. Behind a stage with a high noise figure it hardly counts: in a six-port receiver whose detectors have a 42 dB noise figure, the core with 6 dB to 10 dB of loss adds 0.0001 dB.

The noise is only as good as the loss in the S-parameter data. An EM solve whose mesh has not converged carries its loss error straight into the noise, and on a low-loss block a small fit error is a large share of 1 - |S<sub>21</sub>|<sup>2</sup>.

Structure models need no option. Their resistors are the structure's loss and always carry their thermal noise, and an RLC network with noisy resistors already emits exactly kT(I - S S<sup>H</sup>) of its own S-parameters (Twiss's theorem, checked on the seven extracted structures to about 1e-13 kT, and by `tests/test_inductor_wideband.py` on both wideband inductors, coupled half coils included, to better than 1e-12 kT), so a generator would count the noise twice. What a structure model can miss is loss it does not contain: the Wilkinson model's only resistor is the isolation resistor, so its through path is lossless and noiseless, and a branch-line coupler without *Resistive loss* is noiseless altogether.

### Watching a conversion

Every conversion runs on a worker thread, so the window stays usable while it runs. Progress shows in the **Conversion** panel, under the loaded file name and directly above the Result rows it fills in, and is mirrored into the **Plot** view's header row so switching views does not lose sight of a running fit:

| While it runs | When it ends |
| --- | --- |
| what the fit is doing (`vector fitting, 7 iterations`, `solving 240 of 401 frequencies`) | `conversion complete` in green |
| how long it has been running | the total time, in green next to it |
| a progress bar tracking the real work, not a step count | the bar, full, and all of it stays until the next conversion starts |

Both indicators sit inside panels that already existed, so neither costs any window height.

Two figures are deliberately absent:

- **No estimated time left.** The fraction is not linear in time and cannot be: the fit stage reports a saturating curve, because how many iterations `auto_fit` will take is not knowable in advance. Any remaining-time number derived from it would be guesswork dressed as a measurement.
- **No result summary on the completion line.** The pole count and RMS error are in the Result rows a few lines below it.

More details worth knowing:

- Nothing is hidden once a conversion has started: dragging a spin box moves the bar and rewrites two labels, where showing and hiding them would strobe.
- A failed conversion reads red and leaves the bar where it stopped rather than filling it, since the attempt did not complete.
- Changing controls during a fit does not queue one conversion per change. The running fit finishes, then the newest settings are converted, once.
- If a long fit finishes while you are in another window, the taskbar entry flashes. The result is also just there when you come back.

**Export** writes the conversion that finished, so it is disabled while one is running and never blocks the window to re-fit.

A conversion runs its linear algebra on one thread of the BLAS library (through [threadpoolctl](https://github.com/joblib/threadpoolctl)). Its matrices are small, so a thread pool costs more than it saves: a 7-port receiver core at order 24 with thermal noise converts in 2.2 s instead of 15 minutes with the default 14 threads. Set `OPENBLAS_NUM_THREADS` or `MKL_NUM_THREADS` to choose the count yourself. A simulator started from snp2le keeps its own threads. A program that runs several conversions at once in threads gets its own thread count and its console back when the last one finishes.

### Run a testbench (simulate)

Drop the exported subcircuit into an Xschem testbench, then run it from the GUI:

1. **Load .sch.** Pick the testbench. The **Simulator** auto-selects from the file name (a name containing `vacask` selects VACASK, any other name selects Ngspice) and can be overridden.
2. **Run Simulation.** Both simulators netlist and simulate through Xschem and write their result table to `plot_simulations/data/`, which is imported and overlaid on the plots automatically. The button turns green on success or red on failure. On failure the dialog shows the simulator log.
3. **Show output.** Tick it to show the simulator's console and plot windows. Leave it unticked to run quietly. The result is imported either way.

> [!NOTE]
> A simulator (Xschem plus Ngspice and/or VACASK) is only needed for this step. The conversion and export themselves are pure Python.

### View testbench results

The testbenches follow the `plot_simulations` structure of the [ihp-sg13g2-ams-chip-template](https://github.com/iic-jku/ihp-sg13g2-ams-chip-template): every testbench exports its result table to `testbenches/xschem/plot_simulations/data/`, and the plot scripts next to it write their PNG figures to `testbenches/xschem/plot_simulations/figures/`.

- `plot_n_port_tb_acsp_vacask.py` runs automatically as the VACASK postprocess step of every `*_tb_acsp_vacask.sch` run: it writes both the result table (`data/<testbench>.txt`, the same column naming the Ngspice testbenches use) and the figure (`figures/<testbench>.png`).
- `plot_n_port_tb_acsp_ngspice.py` reproduces the `.control` blocks' plots from the exported Ngspice `wrdata` tables with matplotlib, magnitude and phase over frequency, one figure per testbench. Run it after a quiet Ngspice run (where the `plot` commands are suppressed).
- `ngspice2python.py` is the helper module that loads the `wrdata` columns (the same helper the [ihp-sg13g2-ams-chip-template](https://github.com/iic-jku/ihp-sg13g2-ams-chip-template) plotting scripts use).
- `sparam_plot.py` holds the figure layout both plot scripts draw through, so the Ngspice and VACASK results are directly comparable. An N-port testbench has N x N S-parameters, which is unreadable in a single pair of axes, so the figure is split by excitation port: one column of axes per driven port j, magnitude on top and phase below, leaving only N traces per panel. The color encodes the receiving port i and is the same in every panel, so one legend serves the whole figure.

One script serves every port count: it discovers the exported vectors from the table header (Ngspice) or the `s(i,j)` vector names (VACASK). Without an argument every `*_tb_acsp_ngspice` table in `data/` is plotted. With a testbench name, only that one is:

```bash
python3 testbenches/xschem/plot_simulations/plot_n_port_tb_acsp_ngspice.py
python3 testbenches/xschem/plot_simulations/plot_n_port_tb_acsp_ngspice.py two_port_tb_acsp_ngspice
```

The plot windows open when a display is available. Headless, only the PNGs are written.

### Run the tests

```bash
pytest               # from the repo root
```


## CLI Overview

The same engine is available headlessly for Makefiles and batch use, through the `-b` (batch) flag:

```bash
snp2le -b list-structures
snp2le -b convert <file.sNp> [options]
```

From a source checkout without installing, use `python -m snp2le -b ...` in place of `snp2le -b`. The exit code is non-zero if any conversion fails, and a failed conversion writes nothing and removes the files an earlier run left at its output paths, so a Makefile never takes an old netlist for the result. With several inputs, a file that fails, for whatever reason, is reported as `[FAIL]` and the rest are still converted. Without `-b`, a single file argument opens the GUI on that file instead (see [Run the GUI](https://github.com/iic-jku/snp2le#run-the-gui)).

### `convert` options

| Option | Scope | Description |
| --- | --- | --- |
| `inputs` | both | one or more `.sNp` files or globs |
| `--mode universal\|structure` | both | conversion philosophy (default `universal`) |
| `--structure KEY` | structure | structure key (see `list-structures`, default `inductor-pi`) |
| `--order N` | universal | maximum model order, counted as `n_real + 2 x n_complex`, 2 or more (default 6) |
| `--passive` / `--no-passive` | universal | enforce passivity (default on) |
| `--passivity-ceiling SIGMA` | universal | sigma_max the enforcement works towards, `1.0` to `1.2`, needs `--passive` (default `1.0`) |
| `--thermal-noise` / `--no-thermal-noise` | universal | add the passive's thermal noise, kT(I - S S<sup>H</sup>) at the ports, or emit the noiseless model (default noiseless). A model that is not strictly passive cannot carry it: nothing is written and the exit code is non-zero |
| `--dc-pin` / `--no-dc-pin` | universal | pin the model to the file's 0 Hz sample, so its DC admittance (a coil's DC resistance) is the file's, or leave the DC point to the fit (default on, acts only on a file with a 0 Hz sample) |
| `--dc-pin-fc FREQ` | universal | corner of the DC pin's low-pass, e.g. `1kHz` (default 160 Hz). Above it the band moves by about fc/f, below it the model is the pin's |
| `--dc-island-leak S` | universal | conductance to ground for each DC mode without a DC path, which can help harmonic balance converge (default 0) |
| `--fext FREQ` | structure | extraction frequency, e.g. `7GHz` (default 10 GHz). The wideband inductors have none |
| `--fmin FREQ` | both | lowest frequency used for the fit (default: the file's first point) |
| `--fmax FREQ` | both | highest frequency used for the fit, above 0 Hz (default: the file's last point) |
| `--stages N` | structure | RLGC ladder cells (transmission line), 1 to 10 (default 2) |
| `--iso-r` / `--no-iso-r` | structure | in-phase Wilkinson isolation R or branch-line arm loss (default on) |
| `--basic` | structure | fixed basic topology for the wideband inductors: 1 coil segment, 1 skin section, no substrate coupling |
| `--segments N` | structure | wideband inductors: fixed coil segment count, 1 to 10, per half for `inductor-ct` (default: the fit picks the fewest of 1 to 3 within 10 % of the best) |
| `--substrate VARIANT` | structure | wideband inductors: `auto`, `symmetric`, `asymmetric`, `symmetric+coupling` or `asymmetric+coupling` (`inductor-ct`: no coupling), default `auto` |
| `--peak-q-weight [A]` | structure | wideband inductors: weight L and Q up to 1+A times near the Q peak (A = 2 without a value) |
| `--shunt-accuracy [K]` | structure | wideband inductors: measure substrate errors against at least K x the series branch, for measured or FDTD data (K = 0.01 without a value) |
| `--ct-port {1,2,3}` | structure | `inductor-ct`: center tap port (default: detected from the data) |
| `--format ngspice\|vacask\|both` | both | output dialect(s), default `ngspice`. VACASK writes `.inc` |
| `-o, --output PATH` | both | output path (single input), names the `.SUBCKT`. A file stem that is not a valid name in both dialects is changed for the `.SUBCKT` (`my-model` to `my_model`), with a warning |
| `--values` | both | print the element values (extracted, or the synthesised network's) |
| `--tolerances` | structure | print per-element tolerances at `f_ext` (the inductor, MIM capacitor, line and balun models) |
| `--simulate SCH` | sim | run an Xschem testbench after converting |
| `--simulator ngspice\|vacask` | sim | simulator for `--simulate` (default: auto from `.sch` name) |
| `--show-output` | sim | show the simulator's console and plot windows |
| `--timeout S` | sim | seconds to wait for a `--simulate` result (default 180) |
| `--plot [SPARAMS]` | both | display data-vs-model plots, plus the sim overlay after `--simulate` (e.g. `S11,S21`) |
| `--quiet` | both | suppress the per-file status and `note:` lines (and the progress bar). `[FAIL]` and `[WARN]` lines stay, and with several inputs a line naming the file comes before its `--values` and `--tolerances` tables |
| `--progress` / `--no-progress` | both | force the progress bar on or off (default: on when stderr is a terminal) |

### Examples

```bash
# universal macromodel to an Ngspice netlist
snp2le -b convert coupler.s4p --mode universal --order 12 -o coupler.spice

# structure extraction at 7 GHz, both dialects, print values and tolerances
snp2le -b convert ind.s2p --mode structure --structure inductor-pi \
    --fext 7GHz --format both --values --tolerances

# wideband inductor model, fitted from DC to past the self-resonance (no --fext)
snp2le -b convert snp2le/examples/ind_500pH_ihp-sg13cmos5l.s2p \
    --mode structure --structure inductor-wideband --format both --values

# center-tapped inductor, center tap detected from the data
snp2le -b convert snp2le/examples/ind_ct_n2_d82_w4_s4_ihp-sg13g2.s3p \
    --mode structure --structure inductor-ct --values

# measured inductor: tolerate substrate noise, weight Q around its peak, 2 segments
snp2le -b convert meas.s2p --mode structure --structure inductor-wideband \
    --segments 2 --peak-q-weight --shunt-accuracy

# fit only the 110 to 170 GHz sub-band of a wider EM sweep
snp2le -b convert core.s7p --mode universal --order 24 --fmin 110GHz --fmax 170GHz

# enforce passivity only down to 1.05, keeping accuracy that strict enforcement would cost
snp2le -b convert bpf.s2p --mode universal --order 13 --passivity-ceiling 1.05

# add the passive's thermal noise to the macromodel, both dialects
snp2le -b convert wpd.s3p --mode universal --order 13 --thermal-noise --format both

# a file with a 0 Hz sample is pinned to it by default, so a coil keeps its DC resistance.
# Here the DC modes without a path to ground also get 1 uS, for harmonic balance
snp2le -b convert coil.s2p --mode universal --order 13 --dc-island-leak 1e-6

# convert the BPF, run the 2-port Xschem testbench, and show data vs model vs sim plots
snp2le -b convert snp2le/examples/bpf_ihp-sg13g2.s2p \
    --mode universal --order 13 -o netlist/spice/two_port.spice \
    --simulate testbenches/xschem/two_port_tb_acsp_ngspice.sch --plot
```

> [!NOTE]
> `--simulate` needs Xschem and `--plot` needs a display. If Xschem is not on `PATH`, `--simulate` prints a clear message and the run exits non-zero.


## Available structures

| Key | Model | Ports | Notes |
| --- | --- | --- | --- |
| `inductor-pi` | Inductor | 2 | series R-L plus shunt C/R per port |
| `inductor-wideband` | Inductor (wideband) | 2 | fitted over the whole band, no f_ext, see below |
| `inductor-ct` | Inductor (center tap) | 3 | coupled half coils, center tap detected or `--ct-port`, no f_ext, see below |
| `mim-cap` | MIM capacitor | 2 | series C with parasitic L/R plus shunt C (use it for MOM caps too) |
| `tline-rlgc` | Tline (RLGC) | 2 | transmission line as an N-cell ladder of L-cells (`--stages`) |
| `wilkinson-inphase` | Wilkinson (in-phase) | 3 | optional isolation resistor (`--iso-r`) |
| `wilkinson` | Wilkinson (quadrature) | 3 | quadrature (90 deg) outputs |
| `balun` | Balun (transformer) | 4 | coupled inductors (k, M, n), Qp and Qs |
| `branchline` | Branch-line coupler | 4 | optional fitted arm loss (`--iso-r`) |

New structures plug in by subclassing `snp2le.core.structures.base.Structure` and registering them in `snp2le/core/structures/__init__.py`. They then appear in the GUI dropdown and the CLI automatically.

### Wideband inductors

`inductor-pi` reads its values off at one frequency, so it is exact there and drifts away from it. `inductor-wideband` and `inductor-ct` are fitted over the whole band instead, from the lowest frequency in the data up to 1.2 x the self-resonance frequency (SRF), and reproduce L, Q, the SRF and the S-parameters over that band. They port Volker Mühlhaus' [inductor_fit](https://github.com/VolkerMuehlhaus/lumpedmodel/tree/main/inductor_fit), whose README has the full theory of operation.

- **Model.** A series branch of R<sub>s</sub>, L<sub>s</sub> and two skin sections R<sub>skin</sub> || L<sub>skin</sub> (frequency-dependent R and L from skin and proximity effect), C<sub>s</sub> across the coil, and a C<sub>ox</sub> - (R<sub>si</sub> || C<sub>si</sub>) substrate network at each port. A substrate coupling R<sub>sub12</sub> || C<sub>sub12</sub> is added only where the data needs it and it is physically plausible.
- **Segments.** An electrically long coil (a mm-wave inductor simulated far past its SRF) behaves like a line, so the fit also tries 2 and 3 equal coil segments with the substrate network distributed along the coil, and keeps the fewest within 10 % of the best fit. The values table shows totals, the netlist one set of elements per segment. *Segments* (`--segments`) fixes the count instead, for the same topology across a sweep or a smaller netlist.
- **Symmetry** is decided from the data: port 2 shares port 1's substrate values when the two shunt branches differ by less than 5 %. `--substrate` fixes the variant instead.
- **Center tap.** `inductor-ct` fits a 3-port with two coil ends and the center tap: two half coils coupled with k, R<sub>ct</sub> to the center tap and a substrate network under it, with the inductances, resistances and substrate of the halves tied separately where the data is symmetric. The center tap is the port the data puts in the middle of the coil, where the two coil ends share the weakest transfer admittance, and the Conversion panel names it. *Center tap* (`--ct-port`) sets it instead. The netlist keeps the file's port order. k is the effective coupling including the center tap lead inductance, which terminal data cannot separate from M.
- **Basic model** (`--basic`) fixes the topology at 1 segment, 1 skin section and no substrate coupling, so every fit has the same elements, e.g. for machine-learning data tables.
- **Peak-Q weight** (`--peak-q-weight`, A = 2) weights L and Q up to 1+A times where the data's Q is at least 0.8 x its peak, e.g. for a VCO tank. On the 500 pH example it takes the basic model's Q error near the peak from 4.2 % to 1.6 %, at a little more error elsewhere.
- **Measured data** (`--shunt-accuracy`, K = 0.01) is for measured or FDTD data. At low frequency the substrate branch is a tiny fraction of the series branch (on the 500 pH coil 3e-6 at 10 MHz, 2e-4 at 0.5 GHz, 1.6e-3 at 2 GHz), so a small absolute error in the data swamps it. The option measures substrate errors against at least K x the series branch. On a synthetic coil with S noise of 1e-3 it brings C<sub>ox1</sub> from 18 % to 29 % off back to within 6 % on three noise draws. Clean EM data (e.g. Palace) does not need it.
- **Keep the low-frequency data.** It is what determines the DC resistance and inductance, so a *Fit range* that starts above the file's first point is reported as extrapolated.
- **Elements the data does not determine are named.** After the fit, every element the curvature at the fit lets move at all is moved by 3, 10, 100 and 1000 times, up and down, with the others re-fitted, and one that gets there while the fit's RMS error grows by 0.5 % or less is named in the message line with the factor it reached, a lower bound. Every name stands on such a model, so the check names no element the data pins down, but it can miss one: on 16 synthetic coils with S noise it named 35 of the 48 elements that a full re-fit can move by 3 times. On the bundled 500 pH coil it names R<sub>skin2</sub>, on the center-tapped coil R<sub>skin2</sub> and L<sub>skin2</sub>: the second skin section has its corner above the fit band, where it acts as plain L, and a change of 1e-12 in the data moved the center tap's R<sub>skin2</sub> by 75 %. *Basic model* leaves that section out. The factors depend on where the optimizer stopped, so they can differ between platforms. Noise is another matter: an element that fits the noise is not free, just wrong, so a synthetic coil with 1e-3 of S noise can come back with L<sub>skin1</sub> tens of times off whether or not it is named.

The GUI offers the two weights at their defaults and *Segments* from 1 to 3. Other weights, up to 10 segments and `--substrate` are CLI options.

On `ind_500pH_ihp-sg13cmos5l.s2p` (10 MHz to 50 GHz) the fit picks 3 segments and reproduces S21 to 0.55 % (RMS error over RMS data) and the peak Q11 of 15.3 at 21 GHz as 15.4 at 20.5 GHz. `inductor-pi` misses S21 by 4.3 % to 16 % over the same band, depending on f_ext (2 to 40 GHz). A universal fit at order 6 is closer still (0.009 %), but its elements are not a coil and it is not passive (sigma_max 2.18 at 500 THz, far above the data, so it cannot carry thermal noise). A full fit takes about 2 s for a 2-port and 6 s for the bundled center-tapped coil, the basic model under 1 s, and the center-tapped coil at `--segments 10` about 35 s.


## Cite This Work

```
@misc{2026_snp2le,
  author = {Dorrer, Simon},
  month = jul,
  year = {2026},
  title = {{GitHub Repository of snp2le: A PySide6 Interactive GUI and CLI-based S-Parameter to Lumped-Element Netlist Converter}},
  url = {https://github.com/iic-jku/snp2le},
  doi = {10.5281/zenodo.21189545}
}
```


## Acknowledgements

- The structure-specific extractors (inductor, MIM capacitor, RLGC line) were inspired by Volker Mühlhaus' [lumpedmodel](https://github.com/VolkerMuehlhaus/lumpedmodel). The wideband inductor models (`inductor-wideband`, `inductor-ct`) and the bundled `ind_ct_n2_d82_w4_s4_ihp-sg13g2.s3p` are his inductor_fit and its example, used under Apache-2.0 with his permission.
- The passivity-enforcement strategy for the universal macromodel was adapted from the [COBRA project](https://github.com/DI-PASSIONATE/COBRA).
- Vector fitting is provided by [scikit-rf](https://scikit-rf.org).

<p align="center">
  <img src="https://raw.githubusercontent.com/iic-jku/snp2le/main/snp2le/gui/assets/iicqc_official.svg" alt="Institute for Integrated Circuits and Quantum Computing" height="100">
</p>


## License

Licensed under the **Apache License 2.0**, see [`LICENSE`](https://github.com/iic-jku/snp2le/blob/main/LICENSE).

The repository is [REUSE](https://reuse.software) compliant: every file carries `SPDX-FileCopyrightText` and `SPDX-License-Identifier` tags, either inline (source files) or through [`REUSE.toml`](https://github.com/iic-jku/snp2le/blob/main/REUSE.toml) for files that cannot hold a header (configs, Xschem symbols, generated netlists, example Touchstone data, figures and result tables). The [License Check](https://github.com/iic-jku/snp2le/actions/workflows/license-check.yml) workflow runs `reuse lint` on every push and pull request to `main`, so a new file without licensing information fails CI. Check it locally with:

```bash
pip install 'reuse[charset-normalizer]'
reuse lint
```

When adding a source file, start it with:

```python
# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
```
