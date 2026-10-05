# Repository conventions

Guidance for coding agents and contributors working in this repo (snp2le, a converter from Touchstone `.sNp` S-parameter files to lumped-element netlists, with a CLI and a Qt GUI).

## What this is

- `snp2le` reads a Touchstone `.sNp` file and writes an equivalent lumped-element subcircuit in two dialects: Ngspice (`.spice`) and VACASK/Spectre (`.inc`).
- Two modes: `universal` (scikit-rf vector fit with optional passivity enforcement, any port count) and `structure` (a known physical topology extracted at one frequency, one extractor per structure key).
- `snp2le.core` is pure Python and Qt-free. `snp2le.gui` is a thin PySide6-Essentials layer. The GUI and the CLI both call the single entry point `engine.convert(state, net)` in `snp2le/core/engine.py`, which returns a `Results` dataclass from `snp2le/core/state.py`.
- `README.md` is the user documentation. `doc/architecture.md` covers data flow, threading, internals and known limitations. Read the relevant part before changing behaviour.

## Layout

- `snp2le/__main__.py`: the `snp2le` command (`main`). No argument or one file opens the GUI, `-b` hands the rest to `snp2le/cli.py`.
- `snp2le/core/`: `engine.py` (pipeline), `universal.py` (vector fit, passivity), `structures/` (extractors, registry in `__init__.py`), `ir.py` (dialect-agnostic Circuit IR), `netlist.py` (Ngspice and VACASK renderers), `mna.py`, `dc.py`, `io.py`, `xschem.py`.
- `snp2le/gui/`: Qt widgets only, no maths. `fit_runner.py` runs `engine.convert` on a worker thread, `help_dialog.py` is the in-app guide.
- `snp2le/examples/`: bundled 2-, 3- and 4-port `.sNp` files, shipped as package data and used by the tests.
- `netlist/`, `schematic/xschem/`, `testbenches/xschem/`: exported example netlists, Xschem symbols, and Ngspice/VACASK testbenches with their plot scripts.
- `tests/`: pytest suite. `test_core.py` covers the core, the `test_gui_*.py` files drive the real window offscreen.

## Install and run

Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                    # runtime deps plus pytest, build, twine, reuse

snp2le                                     # GUI, preloaded with snp2le/examples/blc_ihp-sg13g2.s4p
snp2le snp2le/examples/bpf_ihp-sg13g2.s2p  # GUI opened on that file
python -m snp2le                           # GUI from the repo root, without installing snp2le itself

snp2le -b list-structures                  # structure keys and their port counts
snp2le -b convert -h                       # every convert option
snp2le -b convert snp2le/examples/bpf_ihp-sg13g2.s2p --order 13 --format both --values
```

- Start the GUI through `snp2le` or `python -m snp2le`, never as `python snp2le/app.py`: the package import fails that way.
- The last command writes `bpf_ihp-sg13g2.spice` and `bpf_ihp-sg13g2.inc` to the current directory. `-o PATH` sets the path and the `.SUBCKT` name.
- Only `--simulate` and the GUI's Run Simulation need Xschem plus Ngspice or VACASK. Conversion and export are pure Python.

## Test

```bash
pytest                                     # whole suite, from the repo root
pytest tests/test_core.py                  # core only, no Qt
reuse lint                                 # the license check CI runs
```

- CI (`.github/workflows/license-check.yml`) runs only `reuse lint`, on pushes and pull requests to `main`. No workflow runs pytest, so run it before opening a pull request.
- The GUI tests set `QT_QPA_PLATFORM=offscreen` themselves and need no display.
- A behaviour change comes with a test in the same commit, as the recent fixes do.

## Conventions

- Keep `snp2le/core` free of Qt and of `snp2le.gui` imports, so it stays testable without a display.
- Import only PySide6-Essentials modules (`QtCore`, `QtGui`, `QtWidgets`, `QtSvg` today). `tests/test_qt_essentials.py` fails on any PySide6-Addons import and on a `pyproject.toml` that depends on the full `PySide6`.
- A runtime dependency change goes into both `pyproject.toml` and `requirements.txt`. Keep `scikit-rf>=1.12`, the reason is in `doc/architecture.md`.
- A rule that the GUI, the CLI and the engine share lives in one core function the others call, for example `universal.effective_ceiling()` and `universal.clamp_passivity_ceiling()` for the passivity ceiling.
- New structure: subclass `snp2le.core.structures.base.Structure`, implement `extract(net, f_extract, n_segments, iso_r)` returning `(CircuitIR, metrics, rows)`, and register it in `STRUCTURES` in `snp2le/core/structures/__init__.py`. The GUI dropdown and the CLI pick it up from there.
- A change to a control or a CLI option updates `README.md`, `snp2le/gui/help_dialog.py` and, where internals change, `doc/architecture.md` in the same pull request.
- Every new file needs licensing information or CI fails. Source files start with the two-line SPDX header shown in the License section of `README.md`. A file that cannot carry a header gets a path entry in `REUSE.toml`.
- Commit subjects in this history are short, lower case and mostly past tense, with identifiers in backticks, for example ``made `Max order` hold below scikit-rf 1.12 (issue #7)``.

## Changing the conversion path

`engine.convert(state, net)` is the single entry point, so nearly every change in `snp2le/core` lands on a path every existing user already runs. "The default behaviour is unchanged" is not a claim a diff can settle: reading the diff answers a different question, whether the code says what you meant. Regenerate the outputs and byte-diff them instead.

1. Write down the differences you intend before you diff (the pull request description is a good place), so the result reads as confirmation rather than something negotiated afterwards.
2. Produce the outputs twice, once from a detached worktree at the base commit (`git worktree add --detach ../snp2le-base <base-commit>`) and once from your branch, in the same environment. The float tails depend on the BLAS the fit ran on (`doc/architecture.md`).
3. Cover every file in `snp2le/examples/`: both dialects (`res.ngspice` and `res.vacask`), universal mode at two or more orders (for example the default 6 and 13), and every structure whose port count matches the file (`snp2le -b list-structures`). A short script over `io.load_touchstone`, `ConverterState`, `engine.convert` and `structures.structure_items()` does it.
4. Dump the derived values of each `Results` next to the netlists, because identical netlists do not prove the GUI shows identical numbers: `ok`, `error`, `passive`, `sigma_max`, `rms_error`, `n_poles`, `model_order`, `dc` (its `ok` and `margin`, universal mode only), `value_rows`, `value_drift` and `messages`.
5. Print floats with an explicit format such as `format(x, ".17g")`. Six significant digits hide the 1e-16 shifts `tests/test_reproducibility.py` was written to catch, and the `repr` of numpy scalars differs between numpy 1 and 2 (both satisfy `numpy>=1.24`).
6. Run under a fixed `PYTHONHASHSEED`, and before trusting any diff, check that two different seeds give identical output on the base commit.
7. Make sure each run imports the tree you meant. An editable install points at one checkout, so set `PYTHONPATH` to the worktree root and check `snp2le.__file__`.

## Traps

- VACASK has no implicit ground: the VACASK subcircuit uses node `GND`, Ngspice keeps `0`, and a VACASK testbench must declare `ground GND`.
- Resistor noise follows `ir.physical`. Universal-mode resistors are fit artefacts and are written with `noisy=0`, structure-mode resistors are real loss and keep their noise. The reasoning sits above `netlist._NOISY_OFF`.
- `universal.fit_universal` redirects `sys.stdout` and `sys.stderr` for the whole process during a fit, so a GUI traceback raised while a fit runs is swallowed. Remember this when a GUI bug only shows up during a fit.
- At a passivity ceiling of `1.0` the scalings in `universal._enforce_at()` are the identity, which keeps the strict path bit-for-bit what it was. Preserve that.
- The GUI clamps an out-of-range passivity ceiling to the limit it overshot, the CLI refuses it. The difference is deliberate.
- Running a bundled testbench (GUI Run Simulation or `--simulate`) rewrites tracked files: `testbenches/xschem/sim_range.inc`, `testbenches/xschem/sim_range.spice` and the result table under `testbenches/xschem/plot_simulations/data/` (VACASK runs also write the figure). Do not commit them unless the change is about them.

## Do not touch

- `netlist/`: generated by the CLI, never edited by hand. The recipe is in `doc/architecture.md` (Notes / limitations). Regenerate only when a pull request changes the netlist output on purpose, since a re-export on another platform moves the last digits without anything being wrong.
- `snp2le/examples/`: the tests, the GUI's default file and the numbers in `README.md` depend on these files. Add a new example rather than editing one.
- The version, in `pyproject.toml` and `snp2le/__init__.py`. A version bump changes both together.
- `LICENSE` and `LICENSES/`. Change `REUSE.toml` only to annotate a new file that cannot carry a header.

## Git

- Do not amend, squash or rebase commits that are already pushed. Add a follow-up commit, and bring `main` into a feature branch with a merge, as the history does. A pull after a rewrite merges the old commits back: a content change shows up as a conflict in every shared file, and a metadata-only change (a reworded message, a removed trailer) merges silently and restores exactly what the rewrite removed.
- If a rewrite is unavoidable, make it reversible first with `git update-ref refs/backup/<name> <tip>`, then move the branch and push with `--force-with-lease=refs/heads/<branch>:<expected-remote-sha>`, never a bare `--force`. Delete any remote branch that still carries the old commits, so nothing pulls them back, and drop the backup ref (`git update-ref -d refs/backup/<name>`) once the pull request is merged.
- A local branch that still tracks a deleted or rewritten remote branch brings the old commits back on the next pull and push. Run `git branch --unset-upstream` or point it at the new branch with `git branch -u`.
- When several agents or sessions work in one clone, give each its own worktree: `git worktree add -b feature/<topic> ../snp2le-<topic> main`. A branch is private, a checkout is shared state, and sessions that share one checkout switch branches under each other. `git worktree list` shows which worktrees exist.
- Run `git log --oneline -1` and `git status` right before you commit, not only when you start. The tree you began in says nothing about the tree you commit from.

## Writing style

These rules apply to documentation, code comments, commit messages, and pull request descriptions in this repo.

- No em-dashes, no double-hyphen dashes, and no semicolons in prose. Code is exempt. Use commas, colons, periods, or parentheses, and split long sentences instead.
- Plain, factual tone: numbers, paths, and verdicts over adjectives, no filler.
- Never hard-wrap prose at a fixed column. Put each sentence or paragraph on one line and let the editor wrap it. When editing, never reflow neighboring lines.
- Keep comments short and accurate: say what is non-obvious and why, never restate what the code already shows.
- Commits and pull requests carry no AI attribution: no `Co-Authored-By` trailers and no "generated with" lines for any coding agent.
