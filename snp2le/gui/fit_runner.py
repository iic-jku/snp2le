# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""fit_runner.py - runs engine.convert off the GUI thread.

A universal-mode fit of a large N-port takes many seconds, and running it inside
the event loop froze the whole window for that time: no repaint, no progress, no
way to tell a working fit from a hung one.  FitRunner moves the conversion to a
worker thread and leaves the UI live.

Two behaviours are worth knowing about:

- **One fit at a time, newest wins.**  A change made while a fit runs is
  remembered, not queued, so dragging a spin box across five values starts one
  more fit at the end instead of five.  The superseded result is still emitted,
  which keeps the views showing the newest finished model.
- **Progress is sampled, not pushed.**  The worker updates a thread-safe
  `ProgressReporter` and the UI reads `snapshot()` on its own timer.  No Qt
  signal is emitted from the worker thread, and the elapsed display keeps
  ticking even while the fit sits inside one long scikit-rf call that reports
  nothing.
"""
from __future__ import annotations
import copy
from PySide6 import QtCore

from snp2le.core import engine
from snp2le.core.state import Results
from snp2le.core.progress import ProgressReporter

# A worker that outlives shutdown is parked here so Python cannot collect the
# QThread while it still runs (that aborts the process).  The interpreter is on
# its way out when this is used, so the entries are never cleaned up.
_ORPHANS = set()


class _FitThread(QtCore.QThread):
    """Runs one engine.convert and keeps its Results on the object."""

    def __init__(self, state, net, reporter):
        super().__init__(None)                    # never parented: see _ORPHANS
        self._state = state
        self._net = net
        self._reporter = reporter
        self.result = None

    def run(self):
        try:
            self.result = engine.convert(self._state, self._net,
                                         progress=self._reporter)
        except Exception as exc:                  # noqa: BLE001
            # engine.convert already turns conversion failures into ok=False, so
            # reaching here means something unexpected.  It must still not take
            # the window down with it.
            self.result = Results(ok=False, mode=self._state.mode, error=str(exc))


class FitRunner(QtCore.QObject):
    """Owns the worker thread and the progress reporter for one window."""

    started = QtCore.Signal()
    finished = QtCore.Signal(object)              # Results, or None if it was dropped

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread = None
        self._pending = None
        self._reporter = ProgressReporter()

    # ---- driving ---------------------------------------------------------
    def request(self, state, net):
        """Convert `state` against `net`, or remember it if a fit is running.

        `state` is copied, so the caller may keep editing its own ConverterState
        while the worker reads the snapshot it was given.
        """
        job = (copy.deepcopy(state), net)
        if self._thread is not None:
            self._pending = job
            return
        self._start(job)

    def busy(self) -> bool:
        return self._thread is not None

    def has_pending(self) -> bool:
        """True when a newer request is waiting for the running fit to end."""
        return self._pending is not None

    def snapshot(self):
        """Current ProgressState, for the UI's own display timer."""
        return self._reporter.snapshot()

    def shutdown(self, msec=5000):
        """Drop any pending job and wait for the running fit before the UI goes.

        A QThread destroyed while running aborts the process, so a worker that
        outlasts the wait is parked in `_ORPHANS` instead of being collected.
        """
        self._pending = None
        thread = self._thread
        if thread is None:
            return
        try:
            thread.finished.disconnect()
        except (RuntimeError, TypeError):
            pass
        self._thread = None
        if not thread.wait(msec):
            _ORPHANS.add(thread)

    # ---- internals -------------------------------------------------------
    def _start(self, job):
        state, net = job
        self._reporter.start("starting")
        self._thread = _FitThread(state, net, self._reporter)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()
        self.started.emit()

    def _on_thread_finished(self):
        thread, self._thread = self._thread, None
        result = getattr(thread, "result", None)
        if thread is not None:
            thread.deleteLater()
        ok = bool(result is not None and getattr(result, "ok", False))
        self._reporter.finish(ok)
        self.finished.emit(result)
        if self._pending is not None:             # a newer request arrived mid-fit
            job, self._pending = self._pending, None
            self._start(job)
