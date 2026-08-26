"""Feature parity: runner compute_meta_features MUST equal meta_features.compute_features_at_index.

This is the duplication that caused the Wave 8/9 bugs (two copies of feature logic
that can silently diverge). The meta-labeler is only valid if both paths agree.
"""
import numpy as np
import alpha3_dry_runner as R
from scripts import meta_features as MF


def _series(n=210, seed=7):
    r = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(r.normal(0, 0.5, n))
    high = close + np.abs(r.normal(0, 0.3, n))
    low = close - np.abs(r.normal(0, 0.3, n))
    vol = np.abs(r.normal(1000, 200, n)) + 100
    return close, high, low, vol


def test_parity_at_live_idx():
    c, h, l, v = _series()
    idx = 200  # the index the runner actually uses after 201-bar bootstrap
    fr = R.compute_meta_features(c, h, l, v, idx)
    fm = MF.compute_features_at_index(c, h, l, v, idx)
    assert fr is not None and fm is not None
    assert set(fr.keys()) == set(fm.keys()) == set(R.FEATURE_ORDER)
    for f in R.FEATURE_ORDER:
        assert np.isclose(fr[f], fm[f], equal_nan=True), f"mismatch at {f}: {fr[f]} vs {fm[f]}"


def test_parity_at_later_idx():
    c, h, l, v = _series(n=260, seed=3)
    idx = 250
    fr = R.compute_meta_features(c, h, l, v, idx)
    fm = MF.compute_features_at_index(c, h, l, v, idx)
    assert fr is not None and fm is not None
    for f in R.FEATURE_ORDER:
        assert np.isclose(fr[f], fm[f], equal_nan=True), f"mismatch at {f}: {fr[f]} vs {fm[f]}"
    # Verify orderbook features are NaN (not available for historical data)
    for f in ['spread_bps', 'imb_1', 'imb_5', 'depth_5', 'depth_10', 
              'vwap_mid_5', 'kyle_lambda_5', 'spread_roll_10', 'imb_5_roll_20', 'spread_bps_dup']:
        assert np.isnan(fr[f]), f"orderbook feature {f} should be NaN for historical data"
        assert np.isnan(fm[f]), f"orderbook feature {f} should be NaN for historical data"


def test_boundary_asymmetry_documented():
    # Known edge: runner accepts idx==199, meta_features requires idx>=200.
    # Live usage always has 201 bars (idx=200), so this never bites in production,
    # but we record it so a future refactor does not widen the gap.
    c, h, l, v = _series(n=205)
    fr = R.compute_meta_features(c, h, l, v, 199)
    fm = MF.compute_features_at_index(c, h, l, v, 199)
    assert fr is not None          # runner computes at 199
    assert fm is None              # meta_features returns None at 199
