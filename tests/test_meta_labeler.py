"""Meta-labeler loading + prediction sanity (no retraining required)."""
import numpy as np
import alpha3_dry_runner as R
from scripts import meta_features as MF


def test_model_loads():
    model, threshold = R.load_meta_labeler()
    assert model is not None
    assert hasattr(model, 'predict_proba')
    assert isinstance(threshold, float)


def test_feature_order_matches_training():
    # The runner's FEATURE_ORDER must equal the one used at training time.
    assert R.FEATURE_ORDER == MF.FEATURE_ORDER
    assert len(R.FEATURE_ORDER) == 46  # 36 original + 10 orderbook features


def test_predict_proba_in_range():
    model, _ = R.load_meta_labeler()
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
