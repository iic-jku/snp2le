# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""test_reproducibility.py - the same input must give the same model twice.

Converting one file twice has to produce the same numbers, in one process and in
two.  The across-process half is the one that actually caught something: a set of
element names iterated in hash order gave the balun's coupled inductors a
different row order per process, which moved its S-parameters at the 1e-16 level.
That is invisible to a normal test and to a regression dump printed at six
significant digits, and it only shows up as an unexplained diff months later.

Run with:  pytest -q
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                            # noqa: E402
import pytest                                                 # noqa: E402

from snp2le.core import engine, io                            # noqa: E402
from snp2le.core.state import ConverterState                  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "snp2le", "examples")

# The balun is the only structure with coupled inductors, so it is the only one
# that reaches the mutual-inductance stamp this guards.
BALUN = "balun_ihp-sg13cmos5l.s4p"

# Hash the raw bytes of the model.  Reductions are the wrong instrument here and
# it is worth saying why: with the bug present, sum(|S|) and the RMS error are
# bit-identical across seeds and only the individual entries move, so a test
# built on those summaries passes while the model underneath is not reproducible.
_CHILD = """
import hashlib, sys
sys.path.insert(0, {root!r})
import numpy as np
from snp2le.core import engine, io
from snp2le.core.state import ConverterState
net = io.load_touchstone({path!r})
res = engine.convert(ConverterState(mode="structure", structure_key="balun"), net)
model = np.ascontiguousarray(res.model_s)
print(hashlib.sha256(model.tobytes()).hexdigest())
print(hashlib.sha256(res.ngspice.encode()).hexdigest())
print(repr([(lab, val) for lab, val, _unit in res.value_rows]))
"""


def _convert_in_subprocess(hashseed):
    """Convert the balun in a fresh interpreter with a fixed PYTHONHASHSEED."""
    env = dict(os.environ, PYTHONHASHSEED=str(hashseed))
    code = _CHILD.format(root=ROOT, path=os.path.join(EXAMPLES, BALUN))
    out = subprocess.run([sys.executable, "-c", code], env=env, text=True,
                         capture_output=True, timeout=300)
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_a_repeated_conversion_is_identical_in_one_process():
    net = io.load_touchstone(os.path.join(EXAMPLES, BALUN))
    state = ConverterState(mode="structure", structure_key="balun")
    first = engine.convert(state, net)
    second = engine.convert(state, net)
    assert first.ok and second.ok
    assert np.array_equal(first.model_s, second.model_s)   # bitwise, not allclose
    assert first.ngspice == second.ngspice
    assert first.value_rows == second.value_rows


@pytest.mark.parametrize("seeds", [(0, 1), (0, 7)])
def test_a_conversion_does_not_depend_on_the_hash_seed(seeds):
    """Two interpreters, two hash seeds, bit-identical models.

    Guards `mna._coupled_groups`: it used to iterate a set of element names, so
    the coupled-inductor row order (and with it the float accumulation order of
    the stamp) followed the per-process string hashes.
    """
    a, b = (_convert_in_subprocess(s) for s in seeds)
    assert a == b, f"the conversion changed with PYTHONHASHSEED {seeds[0]} vs {seeds[1]}"
