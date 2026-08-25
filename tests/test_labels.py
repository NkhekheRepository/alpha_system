"""Triple-barrier label logic (TP / SL / TIMEOUT classification)."""
import numpy as np
from scripts import generate_labels as GL


def _build(k=5, h=10, entry=101.0, fwd=None):
    n = k + h + 5
    closes = np.full(n, 100.0)
    closes[k] = entry
    for j in range(k + 1, n):
        closes[j] = fwd[j - (k + 1)] if fwd is not None else 101.0
    highs = closes.copy()
    lows = closes.copy()
    # widen high/low slightly so barrier crosses register
    highs = np.maximum(highs, closes + 0.5)
    lows = np.minimum(lows, closes - 0.5)
    return closes, highs, lows


def test_long_tp_hit():
    # entry 101 long; price rises to 105 -> TP (+2% = 103.02) hit
    fwd = [105.0] * 15
    closes, highs, lows = _build(entry=101.0, fwd=fwd)
    labels, *_ = GL.compute_labels_vectorized(closes, highs, lows, k=5, h=10)
    assert labels[0] == 1


def test_long_sl_hit():
    # entry 101 long; price falls to 96 -> SL (−2% = 98.98) hit
    fwd = [96.0] * 15
    closes, highs, lows = _build(entry=101.0, fwd=fwd)
    labels, *_ = GL.compute_labels_vectorized(closes, highs, lows, k=5, h=10)
    assert labels[0] == 0


def test_long_timeout():
    # entry 101 long; price stays flat -> no barrier crossed -> TIMEOUT (NaN)
    fwd = [101.0] * 15
    closes, highs, lows = _build(entry=101.0, fwd=fwd)
    labels, *_ = GL.compute_labels_vectorized(closes, highs, lows, k=5, h=10)
    assert np.isnan(labels[0])


def test_short_direction():
    # closes[k] < closes[0] -> short direction
    closes, highs, lows = _build(entry=99.0)
    _, _, direction, _ = GL.compute_labels_vectorized(closes, highs, lows, k=5, h=10)
    assert direction[0] == -1
