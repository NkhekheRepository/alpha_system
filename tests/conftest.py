"""Shared fixtures for Alpha 3 test suite."""
import numpy as np
import pytest


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def ohlcv(rng):
    """A random-walk OHLCV series of `n` 1m bars (default 210)."""
    def _make(n=210, seed=0):
        r = np.random.default_rng(seed)
        close = 100.0 + np.cumsum(r.normal(0, 0.5, n))
        high = close + np.abs(r.normal(0, 0.3, n))
        low = close - np.abs(r.normal(0, 0.3, n))
        vol = np.abs(r.normal(1000, 200, n)) + 100
        return close, high, low, vol
    return _make


@pytest.fixture
def sample_state():
    return {
        'capital': 100.0,
        'equity': 100.0,
        'effective_equity': 100.0,
        'open_positions': {},
        'total_trades': 0,
    }


@pytest.fixture
def prices():
    return {'BTCUSDT': 90.0, 'ETHUSDT': 2500.0}
