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
    return net


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
