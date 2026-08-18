"""Rule-based factor classification for the prototype.

Real factor exposure is measured via regression against factor return series
(e.g. Fama-French). For the prototype we use transparent rules over available
fundamentals to place each security on five factor axes. Each axis returns a
score in [-1, 1] per security; the portfolio tilt is the value-weighted mean.

Axes (low_label <-> high_label):
  - style:    value <-> growth      (from P/E, P/B)
  - size:     small <-> large       (from market cap)
  - momentum: laggard <-> leader    (from trailing relative return)
  - quality:  low <-> high          (from ROE)
  - beta:     low <-> high          (from beta)
"""
from __future__ import annotations

from app.models import Security

# Axis definitions: (key, low_label, high_label)
FACTOR_AXES: list[tuple[str, str, str]] = [
    ("style", "Value", "Growth"),
    ("size", "Small Cap", "Large Cap"),
    ("momentum", "Laggard", "Leader"),
    ("quality", "Low Quality", "High Quality"),
    ("beta", "Low Beta", "High Beta"),
]


def _clamp(x: float) -> float:
    return max(-1.0, min(1.0, x))


def style_score(sec: Security) -> float | None:
    """Growth (+1) vs Value (-1) from valuation multiples.

    High P/E and P/B => growth. Neutral pivots ~ market averages.
    """
    if sec.pe is None and sec.pb is None:
        return None
    parts: list[float] = []
    if sec.pe is not None:
        parts.append(_clamp((sec.pe - 25.0) / 25.0))
    if sec.pb is not None:
        parts.append(_clamp((sec.pb - 5.0) / 10.0))
    return _clamp(sum(parts) / len(parts))


def size_score(sec: Security) -> float | None:
    """Large (+1) vs Small (-1) from market cap (log scale around ~$50B)."""
    if not sec.market_cap:
        return None
    import math

    # log10($50B) ~ 10.7; scale so mega-caps approach +1, small-caps negative.
    return _clamp((math.log10(sec.market_cap) - 10.7) / 1.5)


def momentum_score(sec: Security) -> float | None:
    """Leader (+1) vs Laggard (-1) from trailing relative return (1.0 = flat)."""
    if sec.momentum is None:
        return None
    return _clamp((sec.momentum - 1.0) / 0.5)


def quality_score(sec: Security) -> float | None:
    """High (+1) vs Low (-1) quality from ROE (pivot ~0.20)."""
    if sec.roe is None:
        return None
    return _clamp((sec.roe - 0.20) / 0.40)


def beta_score(sec: Security) -> float | None:
    """High (+1) vs Low (-1) beta (pivot 1.0)."""
    if sec.beta is None:
        return None
    return _clamp((sec.beta - 1.0) / 0.75)


SCORERS = {
    "style": style_score,
    "size": size_score,
    "momentum": momentum_score,
    "quality": quality_score,
    "beta": beta_score,
}
