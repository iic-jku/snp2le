# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""progress.py - progress reporting for long conversions (pure Python, no Qt).

A universal-mode fit of a large N-port runs for many seconds, and until this
module existed it ran silently: the GUI froze with no sign of life and the CLI
printed nothing until the netlist was already on disk.  The core now reports
through one plain callable,

    callback(fraction, message)

with `fraction` an overall 0..1 estimate of the whole conversion.  Two helpers
sit around that contract:

- `StageTracker` maps a stage's own 0..1 progress onto the overall fraction, so
  each step reports its progress without knowing what the others cost.
- `ProgressReporter` is a thread-safe sink that also keeps elapsed time and an
  ETA.  A GUI samples `snapshot()` on its own timer instead of being called from
  the worker thread, which keeps Qt signal traffic out of the worker and lets
  the elapsed display tick even while the fit sits inside one long scikit-rf
  call.

Progress is optional everywhere: `convert(state, net)` with no `progress=`
argument behaves exactly as it did before.
"""
from __future__ import annotations
from dataclasses import dataclass
import threading
import time

# Below this fraction an ETA is noise (a fraction of a second divided by a
# fraction of a percent), so `snapshot()` reports nan instead of a wild number.
_ETA_MIN_FRACTION = 0.04
_ETA_MIN_ELAPSED = 0.6          # s, do not guess before there is a measurement
_ETA_SMOOTHING = 0.35           # EMA weight of the newest estimate


def null_progress(fraction: float, message: str = "") -> None:
    """Progress sink that discards everything.  The default in every core call."""


@dataclass(frozen=True)
class ProgressState:
    """One consistent reading of a `ProgressReporter`, safe to render."""
    running: bool = False
    fraction: float = 0.0
    message: str = ""
    elapsed: float = 0.0
    eta: float = float("nan")     # seconds left, nan while it cannot be estimated
    ok: bool = True               # outcome of the last finished run


class StageTracker:
    """Turn per-stage progress into one overall fraction.

    `plan` is a sequence of `(key, weight, message)`.  Weights are relative
    costs, not percentages, so a plan can be assembled conditionally (dropping
    the passivity stage when it is switched off) without renormalising by hand.

    The reported fraction is clamped to 0..1 and never decreases: a bar that
    jumps backwards reads as a bug even when the estimate behind it improved.
    """

    def __init__(self, callback=None, plan=()):
        self._cb = callback or null_progress
        # The universal fit reports from a watcher thread while the worker thread
        # reports stage boundaries, so two reports can land together.  The lock is
        # held across the callback as well, which is what makes the sink see them
        # in nondecreasing order rather than merely clamped.
        self._lock = threading.Lock()
        self._offset = {}
        self._weight = {}
        self._message = {}
        plan = [(k, float(w), m) for k, w, m in plan]
        total = sum(w for _, w, _ in plan) or 1.0
        acc = 0.0
        for key, weight, message in plan:
            self._offset[key] = acc / total
            self._weight[key] = weight / total
            self._message[key] = message
            acc += weight
        self._key = None
        self._floor = 0.0

    def enter(self, key, message=None):
        """Start stage `key` and report its opening message."""
        self._key = key
        self._report(self._offset.get(key, self._floor),
                     message or self._message.get(key, ""))

    def tick(self, fraction=0.0, message=None):
        """Report progress *within* the current stage (`fraction` is 0..1 there)."""
        if self._key is None:
            return
        base = self._offset.get(self._key, 0.0)
        span = self._weight.get(self._key, 0.0)
        self._report(base + span * _clamp(fraction),
                     message or self._message.get(self._key, ""))

    def sub(self, key, message=None):
        """Enter stage `key` and return a `callback(fraction, message)` bound to it.

        This is what gets handed to a core routine that knows how to report its
        own 0..1 progress (`mna.rlc_sparams`, `universal.fit_universal`) and
        nothing about the pipeline around it.
        """
        self.enter(key, message)

        def report(fraction, note=""):
            if self._key != key:              # a later stage already started
                return
            self.tick(fraction, note or None)
        return report

    def finish(self, message="done"):
        self._key = None
        self._report(1.0, message)

    def _report(self, fraction, message):
        with self._lock:
            value = max(self._floor, _clamp(fraction))
            self._floor = value
            try:
                self._cb(value, message)
            except Exception:                 # noqa: BLE001
                pass                          # reporting must never break a conversion


class ProgressReporter:
    """Thread-safe progress sink with elapsed time and an ETA.

    The worker thread calls the instance (it *is* the `callback`), the UI thread
    reads `snapshot()`.  Every field is guarded by one lock, so a reading is
    always self-consistent instead of a half-updated mix of two reports.
    """

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._running = False
        self._fraction = 0.0
        self._message = ""
        self._ok = True
        # None, not 0.0: a monotonic clock may legitimately read 0, and a test
        # clock always starts there, so a numeric sentinel would report a run
        # that began at t=0 as one that never began.
        self._t0 = None
        self._t_end = None
        self._eta = float("nan")

    def start(self, message="starting"):
        with self._lock:
            self._running = True
            self._fraction = 0.0
            self._message = message
            self._ok = True
            self._t0 = self._clock()
            self._t_end = None
            self._eta = float("nan")

    def __call__(self, fraction, message=""):
        with self._lock:
            if not self._running:             # a late report from a superseded run
                return
            self._fraction = _clamp(fraction)
            if message:
                self._message = message
            self._eta = self._estimate_eta()

    def finish(self, ok=True, message=""):
        with self._lock:
            self._running = False
            self._ok = bool(ok)
            self._fraction = 1.0
            self._t_end = self._clock()
            self._eta = float("nan")
            if message:
                self._message = message

    def snapshot(self) -> ProgressState:
        with self._lock:
            if self._t0 is None:
                elapsed = 0.0
            else:
                end = self._clock() if self._t_end is None else self._t_end
                elapsed = max(0.0, end - self._t0)
            return ProgressState(running=self._running, fraction=self._fraction,
                                 message=self._message, elapsed=elapsed,
                                 eta=self._eta, ok=self._ok)

    # ---- internals (called with the lock held) ---------------------------
    def _estimate_eta(self):
        elapsed = self._clock() - self._t0
        if self._fraction < _ETA_MIN_FRACTION or elapsed < _ETA_MIN_ELAPSED:
            return float("nan")
        raw = elapsed * (1.0 - self._fraction) / self._fraction
        if self._eta != self._eta:            # nan: this is the first usable estimate
            return raw
        return _ETA_SMOOTHING * raw + (1.0 - _ETA_SMOOTHING) * self._eta


def _clamp(x):
    try:
        value = float(x)
    except (TypeError, ValueError):
        return 0.0
    if value != value:                        # nan
        return 0.0
    return min(1.0, max(0.0, value))


def format_duration(seconds) -> str:
    """Seconds as 'm:ss' from a minute up, else '4.2 s'.  '--' when unknown."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "--"
    if s != s or s < 0:                       # nan or negative
        return "--"
    if s < 60:
        return f"{s:.1f} s"
    minutes, rest = divmod(int(round(s)), 60)
    return f"{minutes}:{rest:02d}"
