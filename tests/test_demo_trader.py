"""demo_trader helpers: quantity rounding and request signing (no network)."""
import demo_trader as DT


def test_round_qty_down_to_step():
    # Force a known step size so no network call happens
    DT._lot_cache['TESTUSDT'] = 0.001
    # 0.004657 -> floor to 0.004 (round DOWN to step)
    assert DT.round_qty('TESTUSDT', 0.004657) == 0.004
    # 0.004999 -> 0.004 (floor, not nearest)
    assert DT.round_qty('TESTUSDT', 0.004999) == 0.004
    # exact step multiple passes through
    assert DT.round_qty('TESTUSDT', 0.005) == 0.005


def test_round_qty_zero_step_passthrough():
    DT._lot_cache['ZUSDT'] = 0.0
    assert DT.round_qty('ZUSDT', 1.234567) == 1.234567


def test_sign_deterministic_and_signed():
    p1 = DT._sign({'symbol': 'BTCUSDT', 'timestamp': 123})
    p2 = DT._sign({'symbol': 'BTCUSDT', 'timestamp': 123})
    assert p1 == p2
    assert 'signature' in p1
    assert len(p1['signature']) == 64  # HMAC-SHA256 hex
    # different timestamp -> different signature
    p3 = DT._sign({'symbol': 'BTCUSDT', 'timestamp': 456})
    assert p3['signature'] != p1['signature']
