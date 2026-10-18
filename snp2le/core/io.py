# SPDX-FileCopyrightText: 2026 Simon Dorrer
# SPDX-License-Identifier: Apache-2.0
"""io.py - load Touchstone (.sNp) files via scikit-rf and summarize them.

The rest of the tool only ever sees an skrf.Network plus a small NetworkInfo
summary, so the file format details stay in one place.  No Qt imports.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import skrf


@dataclass
class NetworkInfo:
    """Lightweight summary of a loaded network, for the UI header."""
    name: str = ""
    n_ports: int = 0
    f_start: float = 0.0       # Hz
    f_stop: float = 0.0        # Hz
    n_points: int = 0
    z0: float = 50.0

    @property
    def summary(self) -> str:
        if not self.n_ports:
            return "No file loaded"
        from .units import format_eng
        return (f"{self.name}  \u00b7  {self.n_ports} ports  \u00b7  "
                f"{format_eng(self.f_start, 'Hz')}\u2013{format_eng(self.f_stop, 'Hz')}"
                f"  \u00b7  {self.n_points} pts")


def load_touchstone(path: str) -> skrf.Network:
    """Load any .sNp file. Raises on failure so the GUI can show a message."""
    net = skrf.Network(path)
    _check_option_references(path, net)
    return net


def _option_references(path: str) -> list:
    """The reference resistances on the file's option line, [] if it gives none."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        for line in fh:
            line = line.split("!", 1)[0].strip()
            if not line.startswith("#"):
                continue
            toks = line[1:].lower().split()
            if "r" not in toks:
                return []
            refs = []
            for tok in toks[toks.index("r") + 1:]:
                try:
                    refs.append(float(tok))
                except ValueError:                 # the options come in any order
                    break
            return refs
    return []


def _check_option_references(path: str, net: skrf.Network) -> None:
    """Refuse an option line with one R per port that scikit-rf did not read as written.

    Touchstone 1.1 allows one reference resistance per port. scikit-rf below 2.2 reads only
    the first and refers every port to it, which models another device without a word."""
    refs = _option_references(path)
    if len(refs) < 2:
        return
    from .units import format_eng
    given = ", ".join(format_eng(r, "ohm") for r in refs)
    if len(refs) != net.nports:
        raise ValueError(f"the option line gives {len(refs)} reference resistances ({given}) "
                         f"for {net.nports} ports")
    read = np.real(np.asarray(net.z0)[0])
    if not np.allclose(read, refs):
        raise ValueError(
            f"the option line gives one reference resistance per port ({given}), which "
            f"scikit-rf {skrf.__version__} reads as "
            f"{', '.join(format_eng(r, 'ohm') for r in read)}. scikit-rf 2.2 and later "
            "read it as written")


# The z0 a conversion works in when the ports do not share one real reference.
REFERENCE_Z0 = 50.0


def uniform_reference(net):
    """Return (`net` with one real reference impedance on every port, notes).

    A network whose ports share one real z0 at every frequency comes back as it is. Any
    other (one per port, complex, varying with frequency) is renormalised to `REFERENCE_Z0`,
    the same device in the single z0 the extractors, the model rebuild and the DC check take.
    Without it they read port 1's z0 for every port."""
    if net is None or len(net.f) == 0:
        return net, []
    z0 = np.asarray(net.z0)
    if np.all(z0 == z0.flat[0]) and np.imag(z0.flat[0]) == 0:
        return net, []
    from .units import format_eng
    if np.all(z0 == z0[0]) and not np.any(np.imag(z0)):
        refs = ", ".join(format_eng(float(r), "ohm") for r in np.real(z0[0]))
        what = f"port references {refs}"
    elif np.all(z0 == z0[0]):
        what = "complex port references"
    else:
        what = "port references that vary with frequency"
    out = net.copy()
    out.renormalize(REFERENCE_Z0)
    return out, [f"{what} renormalised to {format_eng(REFERENCE_Z0, 'ohm')}"]


def info_for(net: skrf.Network) -> NetworkInfo:
    if net is None:
        return NetworkInfo()
    z0 = float(np.real(np.atleast_1d(net.z0).flatten()[0]))
    return NetworkInfo(
        name=net.name or "network",
        n_ports=net.nports,
        f_start=float(net.f[0]),
        f_stop=float(net.f[-1]),
        n_points=len(net.f),
        z0=z0,
    )


def passive_dc(net: skrf.Network, ceiling: float = 1.0):
    """Return (`net` with its 0 Hz point made passive, sigma_max of that point before).

    A DC point extrapolated by an EM solver can come out a hair above passivity (ORCA files
    reach sigma 1.0000173), and a fit that includes it inherits a non-passive DC: a negative
    DC conductance, which stops a harmonic-balance run.  Singular values of S(0) above
    `ceiling` are clipped to it.  Every direction with more loss, a coil's DC resistance
    included, keeps its value.  A network without a 0 Hz point, or with one that is not
    finite, comes back as it is, with NaN."""
    if net is None or len(net.f) == 0 or net.f[0] != 0 or not np.all(np.isfinite(net.s[0])):
        return net, float("nan")
    u, sv, vh = np.linalg.svd(net.s[0])
    if sv[0] <= ceiling:
        return net, float(sv[0])
    out = net.copy()
    out.s[0] = u @ np.diag(np.minimum(sv, ceiling)) @ vh
    return out, float(sv[0])


def without_dc(net: skrf.Network) -> skrf.Network:
    """Return `net` with any DC (f=0) sample removed.

    A 0 Hz point makes the Y-/ABCD-parameter extraction and the MNA rebuild
    divide by omega = 0, so we drop it (scikit-rf interpolation/fitting also
    dislike it).  Networks that already start above DC are returned unchanged.
    """
    if net is None or len(net.f) == 0 or net.f[0] != 0:
        return net
    keep = net.f > 0
    return net[keep]


# A band with fewer samples than this cannot support a meaningful fit, so it is
# rejected with a message instead of producing a model built on 2 points.
_MIN_BAND_POINTS = 4


def _band_text(lo, hi) -> str:
    """The requested band as a phrase, e.g. "110 GHz to 170 GHz", "from 110 GHz",
    "up to 170 GHz". An open side is named as open rather than filled in with a
    number the user never asked for."""
    from .units import format_eng
    if lo is not None and hi is not None:
        return f"{format_eng(lo, 'Hz')} to {format_eng(hi, 'Hz')}"
    if lo is not None:
        return f"from {format_eng(lo, 'Hz')}"
    return f"up to {format_eng(hi, 'Hz')}"


def restrict_band(net, f_min=None, f_max=None):
    """Return (`net` cropped to [f_min, f_max] in Hz, notes).

    `None` (or 0) on either side means "open on that side", so the default is the
    full file. The band is validated against the data: a requested edge that lies
    outside the file is clamped to it and reported in `notes`, an empty or inverted
    band raises ValueError so the caller can show the reason instead of fitting a
    nonsensical subset. `notes` is a list of strings for the UI and the log.
    """
    from .units import format_eng
    notes = []
    if net is None or len(net.f) == 0:
        return net, notes
    lo = None if f_min in (None, 0) else float(f_min)
    hi = None if f_max in (None, 0) else float(f_max)
    if lo is None and hi is None:
        return net, notes

    f = np.asarray(net.f, dtype=float)
    d0, d1 = float(f[0]), float(f[-1])
    if lo is not None and hi is not None and lo >= hi:
        raise ValueError(f"fit range is empty: f_min ({format_eng(lo, 'Hz')}) must be "
                         f"below f_max ({format_eng(hi, 'Hz')})")
    if (lo is not None and lo > d1) or (hi is not None and hi < d0):
        raise ValueError(
            f"requested fit range {_band_text(lo, hi)} lies outside the data "
            f"({format_eng(d0, 'Hz')} to {format_eng(d1, 'Hz')})")
    if lo is not None and lo < d0:
        notes.append(f"f_min {format_eng(lo, 'Hz')} is below the data, "
                     f"fitting from {format_eng(d0, 'Hz')}")
    if hi is not None and hi > d1:
        notes.append(f"f_max {format_eng(hi, 'Hz')} is above the data, "
                     f"fitting up to {format_eng(d1, 'Hz')}")

    keep = np.ones(f.shape, dtype=bool)
    if lo is not None:
        keep &= f >= lo
    if hi is not None:
        keep &= f <= hi
    n_keep = int(np.count_nonzero(keep))
    if n_keep < _MIN_BAND_POINTS:
        raise ValueError(
            f"only {n_keep} data point(s) in the requested fit range "
            f"({_band_text(lo, hi)}), at least "
            f"{_MIN_BAND_POINTS} are needed (the file has {len(f)} points over "
            f"{format_eng(d0, 'Hz')} to {format_eng(d1, 'Hz')})")
    if n_keep == len(f):
        return net, notes
    out = net[keep]
    notes.append(f"fit range {format_eng(float(out.f[0]), 'Hz')} to "
                 f"{format_eng(float(out.f[-1]), 'Hz')} "
                 f"({n_keep} of {len(f)} points)")
    return out, notes


def load_ngspice_sim(path: str) -> dict:
    """Parse an Ngspice S-parameter table into a plain dict for the plot overlay.

    The file is a whitespace-separated table whose first row names the columns,
    e.g.::

        frequency   s11_db   s21_db   ...   s11_deg   s21_deg   ...

    The first three characters of a column name are the S-parameter (``s11`` ->
    ``S11``), the ``_db`` suffix is magnitude in dB and ``_deg`` is phase in
    degrees.  Returns ``{"f": Hz, "S11": {"db": arr, "deg": arr}, ...}``.
    """
    with open(path) as fh:
        lines = [ln for ln in fh if ln.strip()]
    if len(lines) < 2:
        raise ValueError("file has no data rows")
    header = lines[0].split()
    rows = []
    for ln in lines[1:]:
        parts = ln.split()
        if len(parts) != len(header):
            continue                              # skip ragged / comment lines
        try:
            rows.append([float(x) for x in parts])
        except ValueError:
            continue
    if not rows:
        raise ValueError("no numeric data rows found")
    data = np.asarray(rows, dtype=float)
    cols = {name: data[:, i] for i, name in enumerate(header)}

    fname = "frequency" if "frequency" in cols else header[0]
    out: dict = {"f": cols[fname]}
    for name in header:
        if name == fname:
            continue
        key = name[:3].upper()                    # "s11_db" -> "S11"
        low = name.lower()                        # ngspice lower-cases the header names,
        if low.endswith("_db"):                   # but don't rely on it (.sch says s11_dB)
            out.setdefault(key, {})["db"] = cols[name]
        elif low.endswith("_deg"):
            out.setdefault(key, {})["deg"] = cols[name]
    if len(out) < 2:
        raise ValueError("no S-parameter columns (expected names like 's11_db')")
    return out


def demo_network() -> skrf.Network:
    """A synthetic 2-port pi-network (series R-L, shunt C) for first-run/demo."""
    f = skrf.Frequency(0.1, 20, 201, "ghz")
    w = 2 * np.pi * f.f
    Ls, Rs, C = 0.82e-9, 1.4, 40e-15
    ys = 1.0 / (Rs + 1j * w * Ls)
    yp = 1j * w * C
    Y = np.zeros((len(w), 2, 2), dtype=complex)
    Y[:, 0, 0] = ys + yp; Y[:, 0, 1] = -ys
    Y[:, 1, 0] = -ys;     Y[:, 1, 1] = ys + yp
    return skrf.Network(frequency=f, y=Y, z0=50, name="demo_inductor")
