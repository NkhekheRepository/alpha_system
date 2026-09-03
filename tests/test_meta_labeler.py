"""Meta-labeler loading + prediction sanity (no retraining required)."""
import numpy as np
import alpha3_dry_runner as R
from scripts import meta_features as MF


def test_model_loads():
    model, threshold, features = R.load_meta_labeler()
    assert model is not None
    assert hasattr(model, 'predict_proba')
    assert isinstance(threshold, float)
    assert features is not None and len(features) == model.n_features_in_ == 36


def test_feature_order_matches_training():
    # The runner's FEATURE_ORDER must equal the one used at training time.
    assert R.FEATURE_ORDER == MF.FEATURE_ORDER
    assert len(R.FEATURE_ORDER) == 46  # 36 original + 10 orderbook features


def test_predict_proba_in_range():
    model, _, features = R.load_meta_labeler()
    x = np.random.default_rng(0).normal(0, 1, size=(1, 36)).astype(np.float32)
    proba = model.predict_proba(x)
    assert proba.shape == (1, 2)
    assert np.all(proba >= 0) and np.all(proba <= 1)
    # P(win) is the second column
    assert 0.0 <= float(proba[0, 1]) <= 1.0


def test_features_to_array_shape():
    feat = {f: 1.0 for f in R.FEATURE_ORDER}
    arr = R.features_to_array(feat)
    assert arr.shape == (1, 46)
    assert arr.dtype == np.float32


def test_features_to_array_none():
    assert R.features_to_array(None) is None


def test_model_array_selects_training_columns():
    # Inference must use exactly the artifact's training order (36), dropping
    # the 10 live-only orderbook keys even when they are NaN.
    import math
    _, _, features = R.load_meta_labeler()
    feat = {f: 1.0 for f in R.FEATURE_ORDER}
    for f in R.FEATURE_ORDER[36:]:
        feat[f] = float('nan')
    arr = R.features_to_model_array(feat, features)
    assert arr is not None and arr.shape == (1, 36)
    assert not math.isnan(float(arr.sum()))
    assert R.features_to_model_array(None, features) is None
    bad = dict(feat)
    bad[features[0]] = float('nan')
    assert R.features_to_model_array(bad, features) is None
