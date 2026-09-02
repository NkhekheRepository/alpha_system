"""Runner helper sanity: state schema + feature array conversion."""
import numpy as np
import alpha3_dry_runner as R


def test_default_state_schema():
    s = R.default_state()
    for key in ('capital', 'equity', 'effective_equity', 'open_positions',
                'trades', 'total_trades', 'total_wins', 'total_losses',
                'cooldown_remaining', 'stake_pct', 'leverage'):
        assert key in s


def test_features_to_array_shape():
    feat = {f: 1.0 for f in R.FEATURE_ORDER}
    arr = R.features_to_array(feat)
    assert arr.shape == (1, 46)
    assert arr.dtype == np.float32


def test_features_to_array_none():
    assert R.features_to_array(None) is None
