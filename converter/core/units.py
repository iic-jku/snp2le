"""units.py - parse and format engineering-notation numbers (e.g. '0.82n', '50').

Pure Python, no GUI imports.  Mirrors the helper from the filter designer so the
two tools format values identically.
"""
from __future__ import annotations

_PREFIXES = {
    "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "\u00b5": 1e-6, "m": 1e-3,
    "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9, "T": 1e12,
}
_FORMAT_STEPS = [
    (1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"), (1.0, ""),
    (1e-3, "m"), (1e-6, "\u00b5"), (1e-9, "n"), (1e-12, "p"), (1e-15, "f"),
]


def parse_eng(text) -> float:
    if text is None:
        raise ValueError("empty value")
    s = str(text).strip().replace(" ", "")
    if not s:
        raise ValueError("empty value")
    for suffix in ("Hz", "ohm", "Ohm", "\u03a9", "F", "H", "s"):
        if s.endswith(suffix) and len(s) > len(suffix):
            s = s[: -len(suffix)]
            break
    if s and s[-1] in _PREFIXES and not s[-1].isdigit():
        mantissa, prefix = s[:-1], s[-1]
    else:
        mantissa, prefix = s, ""
    try:
        return float(mantissa) * _PREFIXES[prefix]
    except (KeyError, ValueError):
        raise ValueError(f"cannot parse number: {text!r}")


def format_eng(value, unit: str = "", sig: int = 3) -> str:
    if value is None:
        return "\u2014"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "\u2014"
    if v != v or v in (float("inf"), float("-inf")):
        return "\u2014"
    if v == 0:
        return f"0 {unit}".strip()
    sign = "-" if v < 0 else ""
    a = abs(v)
    for scale, prefix in _FORMAT_STEPS:
        if a >= scale:
            return f"{sign}{a / scale:.{sig}g} {prefix}{unit}".strip()
    return f"{v:.{sig}g} {unit}".strip()
