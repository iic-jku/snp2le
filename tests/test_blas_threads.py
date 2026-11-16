# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_blas_threads.py - a conversion runs its linear algebra on one BLAS thread.

A fit's matrices are small, so the BLAS thread pool costs more than it saves.  engine.convert
limits the loaded BLAS libraries to one thread with threadpoolctl, gives them their count back
afterwards, and leaves them alone when the user set OPENBLAS_NUM_THREADS or MKL_NUM_THREADS.
The tests start from 2 threads, so the limit shows even when pytest itself runs on one.
Run with:  pytest -q
"""
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest                                                   # noqa: E402

pytest.importorskip("threadpoolctl")
from threadpoolctl import threadpool_info, threadpool_limits    # noqa: E402

from snp2le.core import engine, io                              # noqa: E402
from snp2le.core.state import ConverterState                    # noqa: E402

_BPF = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "snp2le", "examples", "bpf_ihp-sg13g2.s2p")


def _blas_threads():
    return sorted({i["num_threads"] for i in threadpool_info() if i["user_api"] == "blas"})


def _threads_seen_while_converting():
    """The BLAS thread counts reported from inside a conversion, at every progress step."""
    seen = set()
    res = engine.convert(ConverterState(mode="universal", max_order=6, thermal_noise=True),
                         io.load_touchstone(_BPF),
                         progress=lambda frac, msg: seen.add(tuple(_blas_threads())))
    assert res.ok and res.noise.ok, res.error or res.noise.message
    return seen


@pytest.fixture()
def two_threads():
    import scipy.linalg                     # noqa: F401  load scipy's own BLAS copy too
    with threadpool_limits(limits=2, user_api="blas"):
        if _blas_threads() != [2]:
            pytest.skip(f"cannot set 2 BLAS threads here (found {_blas_threads()})")
        yield


def test_a_conversion_runs_on_one_blas_thread_and_gives_the_count_back(two_threads,
                                                                         monkeypatch):
    for name in engine._BLAS_THREAD_VARS:
        monkeypatch.delenv(name, raising=False)
    assert _threads_seen_while_converting() == {(1,)}
    assert _blas_threads() == [2]


def test_a_thread_count_the_user_set_is_left_alone(two_threads, monkeypatch):
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "2")
    assert _threads_seen_while_converting() == {(2,)}
    assert _blas_threads() == [2]


def test_overlapping_conversions_give_the_count_back(two_threads, monkeypatch):
    """A library caller may run conversions in parallel threads.  Forced overlap: both are
    inside, then the first one leaves before the second.  With a save-and-restore per call
    the second would run on the restored count after the first left, and put back the first
    one's limit at the end, leaving the process on one thread for good."""
    for name in engine._BLAS_THREAD_VARS:
        monkeypatch.delenv(name, raising=False)
    both_inside = threading.Barrier(2, timeout=120)
    first_left = threading.Event()
    seen = []
    real = engine._convert

    def held(*args, **kwargs):
        res = real(*args, **kwargs)
        both_inside.wait()
        seen.append(tuple(_blas_threads()))
        if threading.current_thread().name == "second":
            assert first_left.wait(timeout=120)
            seen.append(tuple(_blas_threads()))     # the first one has left, the limit holds
        return res

    monkeypatch.setattr(engine, "_convert", held)
    net = io.load_touchstone(_BPF)
    results = []

    def run(done=None):
        results.append(engine.convert(ConverterState(mode="universal", max_order=6), net))
        if done is not None:
            done.set()

    first = threading.Thread(target=run, args=(first_left,), name="first")
    second = threading.Thread(target=run, name="second")
    first.start()
    second.start()
    first.join()
    second.join()
    assert len(results) == 2 and all(r.ok for r in results)
    assert seen == [(1,), (1,), (1,)]
    assert _blas_threads() == [2]


def test_each_conversion_on_a_new_thread_runs_on_one_blas_thread(two_threads, monkeypatch):
    """The GUI converts on a new QThread each time, and a finished QThread still counts as alive.
    threadpoolctl 3.8 lets only the thread that set OpenBLAS first set it again while that thread
    lives, so the second fit ran on every BLAS thread."""
    for name in engine._BLAS_THREAD_VARS:
        monkeypatch.delenv(name, raising=False)
    release = threading.Event()
    seen = []

    def fit_and_stay_alive(done):
        try:
            seen.append(_threads_seen_while_converting())
        finally:
            done.set()
        release.wait(timeout=120)

    threads = []
    try:
        for _ in range(2):
            done = threading.Event()
            threads.append(threading.Thread(target=fit_and_stay_alive, args=(done,)))
            threads[-1].start()
            assert done.wait(timeout=300)
    finally:
        release.set()
        for t in threads:
            t.join()
    assert seen == [{(1,)}, {(1,)}]
    assert _blas_threads() == [2]
