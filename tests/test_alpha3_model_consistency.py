"""Alpha 3% meta-labeler MODEL CONSISTENCY suite.

Guards the contract between the three copies of feature logic and the trained
model artifact — the exact class of duplication that caused the Wave 8/9 bugs.

Verified findings this suite encodes (2026-08-31, alpha3learn):
  * _ema (EMA) is now ONE recursive formula in all three paths:
      - alpha3_dry_runner._ema          (live runner)
      - scripts.meta_features._ema      (live validation/backtest path)
      - scripts.engineer_features._ema  (training)
    Previous training _ema used pandas ewm(adjust=True, min_periods=span),
    which diverges in interior values (max abs diff ~0.17 on a test path).
  * The two LIVE copies (runner vs meta_features) are byte-identical in their
    windowing + RSI/MACD conventions and must stay numerically equal — asserted
    exactly in test_live_ema_rsi_macd_parity (also covered by test_features.py).
  * TRAINING vs LIVE RSI uses a DIFFERENT windowing convention:
      - training: EMA over the FULL series, sliced at `[period:]`
      - live:     EMA over the `period`-length tail only, `[-1]`
    This is a documented, DEFERRED-window skew (test asserts a floor so a
    silent convention change is caught) to be resolved together with the pending
    K40 retrain. The model was trained on full-history RSI; live feeds it
    tail-window RSI.
  * The model artifact is K=60 trained; the runner/config are K=60 — matching
    the canonical config (locked in tests/test_config_consistency.py).

All side-effect sinks are isolated by conftest fixtures; these tests are
read-only against the model artifact.
"""

import joblib
import json

import numpy as np
import pytest

import alpha3_dry_runner as R
from scripts import meta_features as MF
from scripts import generate_labels as GL
from scripts import engineer_features as EF
import alpha4_dry_runner as R4


MODEL = joblib.load(R.META_LABELER_PATH)
METRICS = json.load(open(R.META_LABELER_PATH.with_name("meta_labeler_metrics.json")))


def _series(n=210, seed=7):
    r = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(r.normal(0, 0.5, n))
    high = close + np.abs(r.normal(0, 0.3, n))
    low = close - np.abs(r.normal(0, 0.3, n))
    vol = np.abs(r.normal(1000, 200, n)) + 100
    return close, high, low, vol


# ---------------------------------------------------------------------------
# Artifact completeness (G8)
# ---------------------------------------------------------------------------
class TestArtifactCompleteness:
    def test_required_keys_present(self):
        for key in ["model", "features", "threshold", "oof_metrics",
                    "config", "feature_importance", "trained_on", "n_samples"]:
            assert key in MODEL, f"artifact missing key: {key}"

    def test_model_is_classifier(self):
        assert hasattr(MODEL["model"], "predict_proba")
        assert list(MODEL["model"].classes_) == [0, 1]
        assert MODEL["model"].n_features_in_ == 36

    def test_config_has_expected_fields(self):
        for key in ["K", "H", "TP_PCT", "SL_PCT", "FEE_RATE", "HOLDINGS",
                    "PURGE_BARS", "EMBARGO_BARS", "N_SPLITS", "RF_PARAMS"]:
            assert key in MODEL["config"], f"config missing key: {key}"


# ---------------------------------------------------------------------------
# Feature schema identity — runner vs training vs artifact (G2)
# ---------------------------------------------------------------------------
class TestFeatureOrder:
    def test_runner_equals_meta_features(self):
        assert R.FEATURE_ORDER == MF.FEATURE_ORDER
        assert len(R.FEATURE_ORDER) == 36

    def test_runner_equals_training_feature_names(self):
        # The artifact feature list IS the training-time contract, and the
        # live order must equal it (the training CSV columns equal FEATURE_ORDER).
        assert R.FEATURE_ORDER == MODEL["features"]
        assert MF.FEATURE_ORDER == MODEL["features"]

    def test_artifact_features_match_order(self):
        assert MODEL["features"] == R.FEATURE_ORDER

    def test_cross_runner_feature_order_identical(self):
        # Alpha 3 and Alpha 4 must feed the SAME 36 features in the same order.
        assert R.FEATURE_ORDER == R4.FEATURE_ORDER


# ---------------------------------------------------------------------------
# Live parity — the two LIVE inference copies must be numerically equal (G1)
# ---------------------------------------------------------------------------
class TestLiveParity:
    def test_live_ema_rsi_macd_parity(self):
        # Byte-for-byte same feature logic; assert exact (tight) equality,
        # tighter than test_features.py which uses default isclose rtol=1e-5.
        for idx in (200, 250, 300, 400):
            c, h, l, v = _series(n=idx + 11, seed=idx)
            fr = R.compute_meta_features(c, h, l, v, idx)
            fm = MF.compute_features_at_index(c, h, l, v, idx)
            assert fr is not None and fm is not None
            for f in ["rsi_7", "rsi_14", "macd", "macd_signal", "macd_hist"]:
                assert np.isclose(fr[f], fm[f], rtol=1e-9, atol=1e-12), f"{f} @ {idx}"

    def test_ema_single_formula_across_three_files(self):
        # Regression: if anyone reintroduces a pandas-ewm _ema in training,
        # this parity (identical interior values) fails.
        x = _series(seed=1)[0]
        ema_r = R._ema(x, 14)
        ema_m = MF._ema(x, 14)
        ema_e = EF._ema(x, 14)
        assert np.allclose(ema_r, ema_m, equal_nan=True)
        assert np.allclose(ema_e, ema_m, equal_nan=True)


# ---------------------------------------------------------------------------
# Documented TRAIN vs LIVE RSI windowing skew (G1/G4) — deferred until retrain
# ---------------------------------------------------------------------------
class TestTrainingVsLiveRSI:
    def test_training_rsi_differs_from_live_rsi(self):
        """Locks the known (deferred) divergence: training RSI uses full-series
        EMA; live uses period-tail EMA. Until the K30 retrain lands, do not
        silently "fix" one side to match the other — the model was trained on
        the full-history convention, so changing live to full-history without a
        retrain would break the model it currently uses."""
        c, h, l, v = _series(n=210, seed=7)
        idx = 200
        live_feat = R.compute_meta_features(c, h, l, v, idx)
        # Training path: feature dict keyed by name -> array over requested
        # indices (here a single index).
        train_feat = EF.compute_features_at_indices(c, h, l, v, np.array([idx]))
        for period in (7, 14):
            key = f"rsi_{period}"
            live_val = live_feat[key]
            train_val = train_feat[key][0]
            # Assert the two DIFFER (the documented skew is real), so a refactor
            # that silently converges one without the other is caught either way.
            assert not np.isclose(live_val, train_val, rtol=1e-3), \
                f"{key} unexpectedly identical — convention changed?"


# ---------------------------------------------------------------------------
# Threshold alignment with metrics (G9)
# ---------------------------------------------------------------------------
class TestThreshold:
    def test_runner_threshold_matches_metrics_and_artifact(self):
        # Set to 0.60 (2026-09-07): breakeven 34.4% @TP3/SL1.5 K60 H100.
        # The deployed gate is the artifact's embedded threshold and must agree
        # with the runner constant.
        assert R.META_THRESHOLD == MODEL["threshold"] == 0.60
        # meta_labeler_metrics.json records the TRAINING F1-optimum (0.50); the
        # live gate deliberately sits above it — assert the deviation is explicit.
        assert METRICS.get("best_threshold") == 0.50


# ---------------------------------------------------------------------------
# Prediction determinism + NaN handling (G3, G13)
# ---------------------------------------------------------------------------
class TestPrediction:
    def test_deterministic_across_loads(self):
        # RandomForest.predict_proba uses OpenMP threading, so floating-point
        # reduction order can differ by tiny amounts across separate loads.
        # Assert tight (float32-epsilon-level) agreement, not bitwise equality.
        arr = _series()[0][:36].reshape(1, -1).astype(np.float32)
        model_data = joblib.load(R.META_LABELER_PATH)
        p1 = model_data["model"].predict_proba(arr)
        p2 = MODEL["model"].predict_proba(arr)
        assert np.allclose(p1, p2, rtol=1e-6, atol=1e-9)

    def test_features_to_array_nan_passthrough(self):
        d = {f: 0.0 for f in R.FEATURE_ORDER}
        d["rsi_7"] = np.nan
        arr = R.features_to_array(d)
        assert arr.shape == (1, 36)
        assert arr.dtype == np.float32
        assert np.isnan(arr[0, R.FEATURE_ORDER.index("rsi_7")])


# ---------------------------------------------------------------------------
# Model performance floor (G12) — degraded retrains must fail loudly
# ---------------------------------------------------------------------------
class TestModelFloor:
    def test_oof_auc_floor(self):
        auc = METRICS["oof_metrics"]["oof_auc"]
        # 0.5 = no skill. Require >= 0.52 to be above random but tolerant of the
        # honest ~0.54 AUC (modest lift consistent with program NO-GO findings).
        assert auc >= 0.52, f"oof_auc {auc} below floor 0.52 — model degraded?"

    def test_oof_metrics_present_and_sane(self):
        m = METRICS["oof_metrics"]
        assert 0.5 <= m["oof_accuracy"] <= 1.0
        assert 0.0 <= m["oof_precision"] <= 1.0
        assert 0.0 <= m["oof_recall"] <= 1.0


# ---------------------------------------------------------------------------
# Label correctness for SHORT side + barrier priority (G6, G7)
# ---------------------------------------------------------------------------
def _paths(entry=105.0):
    """Deterministic arrays with prior bars at 100, signal bar at `entry`
    (entry>100 -> long, entry<100 -> short). Values = (high+low)/2 by default."""
    k, h = 5, 10
    n = k + h + 5
    closes = np.full(n, 100.0)
    closes[k] = entry
    highs = np.full(n, entry)
    lows = np.full(n, entry)
    return closes, highs, lows, k, h, n, entry


class TestShortLabels:
    def test_short_tp_hit(self):
        # Entry 100 short; price DROPS to 96 -> TP (-2% -> 98.0) hit first.
        closes, highs, lows, k, h, n, entry = _paths(entry=99.0)
        for j in range(k + 1, n):
            highs[j] = 99.0
            lows[j] = 95.0
        labels, barrier_bars, direction, _ = GL.compute_labels_vectorized(
            closes, highs, lows, k=k, h=h, tp=0.02, sl=-0.02)
        assert direction[0] == -1
        assert labels[0] == 1, f"short TP expected label 1, got {labels[0]}"

    def test_short_sl_hit(self):
        # Entry 100 short; price RISES to 104 -> SL (+2% -> 102.0) hit first.
        closes, highs, lows, k, h, n, entry = _paths(entry=99.0)
        for j in range(k + 1, n):
            highs[j] = 103.0
            lows[j] = 103.0
        labels, barrier_bars, direction, _ = GL.compute_labels_vectorized(
            closes, highs, lows, k=k, h=h, tp=0.02, sl=-0.02)
        assert direction[0] == -1
        assert labels[0] == 0, f"short SL expected label 0, got {labels[0]}"


class TestBarrierPriority:
    def test_tp_before_sl_is_win(self):
        # Entry 105 (long): TP = 107.1, SL = 102.9. Path hits TP on bar 1
        # (high 107.1), SL only on bar 3 (low 102.9). TP-first -> label 1.
        closes, highs, lows, k, h, n, entry = _paths(entry=105.0)
        tp, sl = entry * 1.02, entry * 0.98
        for j in range(k + 1, n):
            bar = j - (k + 1)
            highs[j] = 106.0
            lows[j] = 103.5
            if bar == 1:
                highs[j] = tp
            elif bar == 3:
                lows[j] = sl
            closes[j] = (highs[j] + lows[j]) / 2
        labels, _, direction, _ = GL.compute_labels_vectorized(
            closes, highs, lows, k=k, h=h, tp=0.02, sl=-0.02)
        assert direction[0] == 1
        assert labels[0] == 1, f"expected 1 (TP-first), got {labels[0]}"

    def test_sl_before_tp_is_loss(self):
        # Entry 105 (long): TP = 107.1, SL = 102.9. Path hits SL on bar 1
        # (low 102.9), TP only on bar 3 (high 107.1). SL-first -> label 0.
        closes, highs, lows, k, h, n, entry = _paths(entry=105.0)
        tp, sl = entry * 1.02, entry * 0.98
        for j in range(k + 1, n):
            bar = j - (k + 1)
            highs[j] = 106.0
            lows[j] = 103.5
            if bar == 1:
                lows[j] = sl
            elif bar == 3:
                highs[j] = tp
            closes[j] = (highs[j] + lows[j]) / 2
        labels, _, direction, _ = GL.compute_labels_vectorized(
            closes, highs, lows, k=k, h=h, tp=0.02, sl=-0.02)
        assert direction[0] == 1
        assert labels[0] == 0, f"expected 0 (SL-first), got {labels[0]}"
