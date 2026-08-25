"""Effective-equity tracking (capital + unrealized P&L), mirrors Alpha 1."""
import numpy as np
import alpha3_dry_runner as R


def test_long_unrealized_profit():
    state = {'capital': 100.0, 'open_positions': {
        'BTCUSDT': {'entry_price': 100.0, 'quantity': 1.0, 'direction': 'long'}}}
    eff = R.get_effective_equity(state, {'BTCUSDT': 110.0})
    assert np.isclose(eff, 110.0)


def test_short_unrealized_profit():
    state = {'capital': 100.0, 'open_positions': {
        'BTCUSDT': {'entry_price': 100.0, 'quantity': 1.0, 'direction': 'short'}}}
    # short profits when price drops below entry
    eff = R.get_effective_equity(state, {'BTCUSDT': 90.0})
    assert np.isclose(eff, 90.0)


def test_multiple_positions_sum():
    state = {'capital': 100.0, 'open_positions': {
        'BTCUSDT': {'entry_price': 100.0, 'quantity': 1.0},
        'ETHUSDT': {'entry_price': 200.0, 'quantity': 2.0}}}
    prices = {'BTCUSDT': 105.0, 'ETHUSDT': 190.0}
    eff = R.get_effective_equity(state, prices)
    # 100 + (105-100)*1 + (190-200)*2 = 100 + 5 - 20 = 85
    assert np.isclose(eff, 85.0)


def test_missing_price_skipped():
    state = {'capital': 100.0, 'open_positions': {
        'BTCUSDT': {'entry_price': 100.0, 'quantity': 1.0}}}
    eff = R.get_effective_equity(state, {})  # no price for BTCUSDT
    assert np.isclose(eff, 100.0)


def test_non_dict_positions_returns_capital():
    state = {'capital': 100.0, 'open_positions': None}
    assert np.isclose(R.get_effective_equity(state, {'BTCUSDT': 90.0}), 100.0)
