"""Kill switch tests: human-in-the-loop close-all-once + COOL, manual triggers."""
import csv
import json
from pathlib import Path

import alpha3_dry_runner as R


def _seed_state(with_position=False):
    s = R.default_state()
    s['kill_armed'] = False
    s['trading_enabled'] = True
    if with_position:
        s['open_positions']['BTCUSDT'] = {
            'symbol': 'BTCUSDT', 'direction': 'long',
            'entry_price': 100.0, 'quantity': 0.1,
            'notional': 10.0, 'age': 1,
            'tp_price': 102.0, 'sl_price': 98.0,
            'entry_time': '2026-01-01T00:00:00',
        }
    return s


def test_default_state_has_kill_fields():
    s = R.default_state()
    assert s['kill_armed'] is False
    assert s['best_return_pct'] == 0.0
    assert s['worst_drawdown_pct'] == 0.0


def test_engage_flattens_open_positions(monkeypatch, tmp_path):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    monkeypatch.setattr(R, 'get_price', lambda s: 105.0)  # long entry 100 -> +5% profit
    monkeypatch.setattr(R, 'KILL_LOG', tmp_path / 'kill_log.csv')
    s = _seed_state(with_position=True)
    R.engage_kill_switch(s)
    assert s['open_positions'] == {}
    assert s['kill_armed'] is True
    assert s['trading_enabled'] is False
    # PnL booked into equity + trade log
    assert len(s['trades']) == 1
    assert s['trades'][0]['reason'] == 'KILL'
    assert s['equity'] > 100.0  # profit realized
    # kill ledger written
    assert R.KILL_LOG.exists()
    rows = list(csv.reader(open(R.KILL_LOG)))
    assert rows[0][3] == 'kill_pnl_total'
    assert float(rows[1][3]) > 0  # positive kill PnL recorded


def test_engage_is_idempotent(monkeypatch):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    monkeypatch.setattr(R, 'get_price', lambda s: 105.0)
    s = _seed_state(with_position=True)
    R.engage_kill_switch(s)
    s['open_positions']['ETHUSDT'] = {'symbol': 'ETHUSDT', 'direction': 'short',
                                      'entry_price': 50.0, 'quantity': 0.2}
    R.engage_kill_switch(s)
    assert s['open_positions'] == {}
    assert s['kill_armed'] is True


def test_disarm_reenables(monkeypatch):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    s = _seed_state(with_position=True)
    R.engage_kill_switch(s)
    R.disarm_kill_switch(s)
    assert s['kill_armed'] is False
    assert s['trading_enabled'] is True


def test_kill_blocks_new_entries(monkeypatch):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    monkeypatch.setattr(R, 'get_ohlcv',
                        lambda s: {'open': 1, 'high': 1, 'low': 1,
                                   'close': 1, 'volume': 1, 'close_time': 0})
    s = _seed_state()
    s['kill_armed'] = True
    R.run_cycle(s, meta_model=None)
    assert s['open_positions'] == {}
    assert s['kill_armed'] is True


def test_cmd_file_kill_and_disarm(monkeypatch, tmp_path):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    monkeypatch.setattr(R, 'get_price', lambda s: 105.0)
    cmd = tmp_path / 'alpha3_cmd.json'
    monkeypatch.setattr(R, 'CMD_FILE', cmd)
    s = _seed_state(with_position=True)
    cmd.write_text(json.dumps({'action': 'kill'}))
    R.check_commands(s)
    assert s['kill_armed'] is True
    assert s['open_positions'] == {}
    assert len(s['trades']) == 1
    cmd.write_text(json.dumps({'action': 'disarm'}))
    R.check_commands(s)
    assert s['kill_armed'] is False
    assert s['trading_enabled'] is True


def test_kill_flag_file_triggers(monkeypatch, tmp_path):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    monkeypatch.setattr(R, 'get_price', lambda s: 105.0)
    flag = tmp_path / 'alpha3_kill.flag'
    monkeypatch.setattr(R, 'KILL_FILE', flag)
    flag.touch()
    s = _seed_state(with_position=True)
    R.check_commands(s)
    assert s['kill_armed'] is True
    assert s['open_positions'] == {}


def test_kill_ledger_records_metrics(monkeypatch, tmp_path):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    monkeypatch.setattr(R, 'get_price', lambda s: 105.0)
    monkeypatch.setattr(R, 'KILL_LOG', tmp_path / 'kill_log.csv')
    s = _seed_state(with_position=True)
    R.engage_kill_switch(s)
    rows = list(csv.reader(open(R.KILL_LOG)))
    assert rows[0][3] == 'kill_pnl_total'
    rec = rows[1]
    assert rec[4] == '1'                       # n_closed
    assert rec[5] == 'BTCUSDT'                 # symbols
    assert float(rec[3]) > 0                   # kill PnL
    assert float(rec[1]) == 100.0              # equity_before
    assert float(rec[2]) > 100.0               # equity_after (profit)


def test_pause_keeps_positions(monkeypatch, tmp_path):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    cmd = tmp_path / 'alpha3_cmd.json'
    monkeypatch.setattr(R, 'CMD_FILE', cmd)
    s = _seed_state(with_position=True)
    cmd.write_text(json.dumps({'action': 'stop'}))
    R.check_commands(s)
    assert s['kill_armed'] is False
    assert s['trading_enabled'] is False
    assert 'BTCUSDT' in s['open_positions']


def test_best_worst_tracking(monkeypatch):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    s = R.default_state()
    s['start_capital'] = 100.0
    s['equity'] = 110.0
    s['effective_equity'] = 110.0
    s['peak_equity'] = 110.0
    R._track_best_worst(s, 110.0)
    assert s['best_return_pct'] == 0.10
    assert s['worst_drawdown_pct'] == 0.0
    R._track_best_worst(s, 99.0)
    assert s['worst_drawdown_pct'] == 0.10
    assert s['best_return_pct'] == 0.10


def test_flatten_does_not_arm(monkeypatch):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    monkeypatch.setattr(R, 'get_price', lambda s: 105.0)
    s = _seed_state(with_position=True)
    R._flatten_positions(s)
    assert s['open_positions'] == {}
    assert s['kill_armed'] is False          # flatten != arm
    assert s['trading_enabled'] is True


def test_kill_clears_circuit_breaker(monkeypatch):
    monkeypatch.setattr(R, 'DEMO_LIVE', False)
    monkeypatch.setattr(R, 'get_price', lambda s: 105.0)
    s = _seed_state(with_position=True)
    s['consecutive_losses'] = 3
    s['cooldown_remaining'] = 40
    R.engage_kill_switch(s)
    assert s['kill_armed'] is True
    assert s['consecutive_losses'] == 0     # breaker reset by human kill
    assert s['cooldown_remaining'] == 0
