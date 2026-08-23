# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_progress.py - the conversion progress plumbing, without Qt.

Covers the things a progress bar can get wrong and nobody notices until a user
is watching a 30 s fit: a fraction that jumps backwards, a reading assembled from
two half-updated reports, and a fit phase that reports nothing at all because the
underlying library has no callback.  Run with:  pytest -q
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                        # noqa: E402
import pytest                                             # noqa: E402

from snp2le.core import engine, io                        # noqa: E402
from snp2le.core.progress import (ProgressReporter, StageTracker,    # noqa: E402
                                  format_duration)
from snp2le.core.state import ConverterState              # noqa: E402
from snp2le.core.universal import _fit_watch              # noqa: E402

PLAN = (("a", 1, "stage a"), ("b", 3, "stage b"))          # a is 25 %, b is 75 %


def _recorder():
    seen = []
    return seen, lambda f, m="": seen.append((f, m))


# ---- StageTracker --------------------------------------------------------
def test_stage_weights_map_onto_the_overall_fraction():
    """A stage's own 0..1 lands inside its weighted slice of the whole run."""
    seen, cb = _recorder()
    track = StageTracker(cb, PLAN)
    track.enter("a")
    track.tick(0.5)
    track.enter("b")
    track.tick(0.5)
    track.finish("done")
    assert [round(f, 4) for f, _ in seen] == [0.0, 0.125, 0.25, 0.625, 1.0]


def test_the_fraction_never_goes_backwards():
    """Out-of-order reports are clamped up, not rendered as a shrinking bar."""
    seen, cb = _recorder()
    track = StageTracker(cb, PLAN)
    track.enter("b")                       # jump straight to the late stage
    track.tick(0.8)
    track.enter("a")                       # then report an earlier one
    assert [f for f, _ in seen] == sorted(f for f, _ in seen)
    assert seen[-1][0] == pytest.approx(0.85)


def test_a_stale_sub_callback_is_ignored():
    """A worker thread reporting after its stage ended must not rewind the bar."""
    seen, cb = _recorder()
    track = StageTracker(cb, PLAN)
    stale = track.sub("a")
    track.enter("b")
    before = len(seen)
    stale(1.0, "late report from stage a")
    assert len(seen) == before


def test_a_raising_callback_cannot_break_a_conversion():
    def boom(fraction, message=""):
        raise RuntimeError("the UI blew up")

    track = StageTracker(boom, PLAN)
    track.enter("a")                       # must not propagate
    track.finish()


def test_reports_stay_ordered_across_threads():
    """The fit watcher and the worker report concurrently, see StageTracker._report."""
    seen, cb = _recorder()
    track = StageTracker(cb, (("s", 1, "s"),))
    track.enter("s")

    def spam(lo):
        for i in range(200):
            track.tick(lo + i / 1000.0)

    threads = [threading.Thread(target=spam, args=(x,)) for x in (0.0, 0.2, 0.5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    values = [f for f, _ in seen]
    assert values == sorted(values)


# ---- ProgressReporter ----------------------------------------------------
class _Clock:
    """A hand-cranked monotonic clock, so the ETA maths is deterministic."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_reporter_tracks_elapsed_and_freezes_it_on_finish():
    clock = _Clock()
    rep = ProgressReporter(clock=clock)
    rep.start()
    clock.t = 4.0
    rep(0.5, "halfway")
    assert rep.snapshot().elapsed == pytest.approx(4.0)
    rep.finish(ok=True)
    clock.t = 99.0                                   # time moves on, the run is over
    snap = rep.snapshot()
    assert snap.elapsed == pytest.approx(4.0) and not snap.running and snap.ok


def test_no_time_remaining_is_offered():
    """The fraction is not linear in time, so the reporter must not publish an
    estimate derived from it.  See the module docstring in core/progress.py."""
    rep = ProgressReporter(clock=_Clock())
    rep.start()
    rep(0.5, "halfway")
    assert not hasattr(rep.snapshot(), "eta")


def test_reports_after_finish_are_ignored():
    """A superseded worker's last report must not revive the finished state."""
    rep = ProgressReporter(clock=_Clock())
    rep.start()
    rep.finish(ok=False, message="failed")
    rep(0.3, "stale")
    snap = rep.snapshot()
    assert not snap.running and snap.message == "failed" and snap.fraction == 1.0


def test_format_duration():
    assert format_duration(4.25) == "4.2 s"
    assert format_duration(75) == "1:15"
    assert format_duration(float("nan")) == "--"
    assert format_duration(None) == "--"


# ---- the fit watcher -----------------------------------------------------
class _FakeFit:
    """Stands in for a VectorFitting mid-auto_fit: a history list that grows."""

    def __init__(self):
        self.d_res_history = []


def test_fit_watch_reports_while_the_fit_is_blocked():
    """scikit-rf's auto_fit has no callback, so progress comes from its history.

    This is the whole reason the universal fit shows movement at all: without
    the watcher the bar would sit still for the entire fit and then jump.
    """
    seen, cb = _recorder()
    vf = _FakeFit()
    with _fit_watch(vf, cb):
        for _ in range(6):                            # the 'fit' runs and iterates
            time.sleep(0.08)
            vf.d_res_history.append(1.0)
    assert len(seen) >= 2, "the watcher never reported"
    values = [f for f, _ in seen]
    assert values == sorted(values), "reported fraction went backwards"
    assert max(values) < 1.0, "an open-ended fit must never report 100 %"
    assert "iteration" in seen[-1][1]


def test_fit_watch_stops_with_the_fit():
    vf = _FakeFit()
    seen, cb = _recorder()
    with _fit_watch(vf, cb):
        time.sleep(0.2)
    before = len(seen)
    time.sleep(0.4)
    assert len(seen) == before, "the watcher outlived the fit"
    assert not any(t.name == "snp2le-fit-watch" and t.is_alive()
                   for t in threading.enumerate())


# ---- end to end through engine.convert -----------------------------------
def _example(name):
    return io.load_touchstone(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "snp2le", "examples", name))


@pytest.mark.parametrize("state,name", [
    (ConverterState(mode="universal", max_order=8), "bpf_ihp-sg13g2.s2p"),
    (ConverterState(mode="structure", structure_key="mim-cap"),
     "mim_cap_170fF_ihp-sg13g2.s2p"),
])
def test_convert_reports_a_full_monotonic_sweep(state, name):
    seen, cb = _recorder()
    res = engine.convert(state, _example(name), progress=cb)
    assert res.ok, res.error
    values = [f for f, _ in seen]
    assert values and values == sorted(values)
    assert values[0] == 0.0 and values[-1] == 1.0
    assert all(0.0 <= v <= 1.0 for v in values)
    assert len(values) > 5, "too coarse to read as progress"
    assert seen[-1][1], "the closing report must say what came out"


def test_convert_without_progress_is_unchanged():
    """The progress argument is optional and must not touch the result."""
    net = _example("bpf_ihp-sg13g2.s2p")
    state = ConverterState(mode="universal", max_order=8)
    quiet = engine.convert(state, net)
    watched = engine.convert(state, net, progress=lambda f, m="": None)
    assert quiet.ok and watched.ok
    assert quiet.ngspice == watched.ngspice
    assert np.allclose(quiet.model_s, watched.model_s)


def test_a_failed_conversion_still_returns_a_result():
    """A progress run that fails reports the error, it does not raise through."""
    seen, cb = _recorder()
    res = engine.convert(ConverterState(mode="structure", structure_key="mim-cap"),
                         _example("wpd_ihp-sg13g2.s3p"), progress=cb)
    assert not res.ok and res.error
    assert [f for f, _ in seen] == sorted(f for f, _ in seen)


# ---- defensive paths -----------------------------------------------------
def test_a_tick_before_any_stage_is_ignored():
    """`sub()` hands its callback out before the stage runs; a report that arrives
    before `enter` must not be scaled against a stage that was never chosen."""
    seen, cb = _recorder()
    track = StageTracker(cb, PLAN)
    track.tick(0.5)
    assert seen == []


def test_snapshot_before_start_is_empty_not_a_crash():
    """The UI's display timer can fire before the first conversion begins."""
    snap = ProgressReporter(clock=_Clock()).snapshot()
    assert snap.elapsed == 0.0 and not snap.running and snap.fraction == 0.0


@pytest.mark.parametrize("value,expected", [
    (float("nan"), 0.0), (None, 0.0), ("nonsense", 0.0),
    (-3.0, 0.0), (7.5, 1.0), (0.25, 0.25),
])
def test_a_nonsense_fraction_cannot_reach_the_bar(value, expected):
    """The fraction crosses a thread boundary into a QProgressBar, so anything a
    core routine can produce (a NaN from a zero-length sweep, a stray None) has to
    land inside 0..1 rather than raise or paint garbage."""
    seen, cb = _recorder()
    rep = ProgressReporter(clock=_Clock())
    rep.start()
    rep(value, "")
    assert rep.snapshot().fraction == expected
    StageTracker(cb, (("only", 1, "only"),)).enter("only")
    assert 0.0 <= seen[0][0] <= 1.0
