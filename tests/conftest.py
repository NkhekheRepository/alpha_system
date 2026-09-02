"""Shared fixtures for Alpha 3 / Alpha 4 test suites."""
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def isolate_alpha4_side_effects(tmp_path, monkeypatch):
    """HARD GATE: no Alpha 4 test may write production ledgers or send Telegram.

    Mirrors the Alpha 3 isolation incident 2026-08-25: redirect every Alpha 4
    side-effect sink (state/ledger/log/command/kill files and Telegram notify +
    audit) to tmp_path. Tests that need specific paths keep their own
    monkeypatches (applied after this autouse fixture, so theirs win).
    """
    import alpha4_dry_runner as R4

    # DATA_DIR is where save_state creates its atomic .tmp file (then
    # os.replace to STATE_FILE). Pinning it is mandatory or a save would drop a
    # .alpha4_state.*.tmp into production dry_data/.
    monkeypatch.setattr(R4, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(R4, 'KILL_LOG', tmp_path / 'alpha4_kill_log.csv')
    monkeypatch.setattr(R4, 'TRADE_LOG', tmp_path / 'alpha4_trades.csv')
    monkeypatch.setattr(R4, 'EQUITY_LOG', tmp_path / 'alpha4_equity.csv')
    monkeypatch.setattr(R4, 'STATE_FILE', tmp_path / 'alpha4_state.json')
    monkeypatch.setattr(R4, 'CMD_FILE', tmp_path / 'alpha4_cmd.json')
    monkeypatch.setattr(R4, 'KILL_FILE', tmp_path / 'alpha4_kill.flag')
    monkeypatch.setattr(R4, '_notify', lambda *a, **k: None)
    monkeypatch.setattr(R4, 'log_event', lambda *a, **k: None)
    yield


@pytest.fixture(autouse=True)
def isolate_production_side_effects(tmp_path, monkeypatch):
    """HARD GATE: no test may ever write production ledgers or send Telegram.

    Incident 2026-08-25: kill-switch tests engaged engage_kill_switch against
    in-memory states but the module-level KILL_LOG / log_trade / _notify /
    log_event globals still pointed at dry_data/* and Telegram — the suite
    appended fake rows to alpha3_kill_log.csv (incl. a +$7,860 BTC row from an
    unmocked get_price hitting live prices) and pushed real KILL alerts to the
    user's chat. Every test now runs with all side-effect sinks redirected to
    tmp_path; tests that need specific paths keep their own monkeypatches
    (theirs win — applied after this fixture).
    """
    import alpha3_dry_runner as R

    # DATA_DIR is where save_state creates its atomic .tmp file (then
    # os.replace to STATE_FILE). Pinning it is mandatory or a save would drop a
    # .alpha3_state.*.tmp into production dry_data/.
    monkeypatch.setattr(R, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(R, 'KILL_LOG', tmp_path / 'kill_log.csv')
    monkeypatch.setattr(R, 'TRADE_LOG', tmp_path / 'trades.csv')
    monkeypatch.setattr(R, 'EQUITY_LOG', tmp_path / 'equity.csv')
    monkeypatch.setattr(R, 'STATE_FILE', tmp_path / 'state.json')
    monkeypatch.setattr(R, 'CMD_FILE', tmp_path / 'cmd.json')
    monkeypatch.setattr(R, 'KILL_FILE', tmp_path / 'kill.flag')
    monkeypatch.setattr(R, '_notify', lambda *a, **k: None)
    monkeypatch.setattr(R, 'log_event', lambda *a, **k: None)
    yield


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
