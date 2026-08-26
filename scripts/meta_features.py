#!/usr/bin/env python3
"""Meta-labeler feature computation for live runner.

Computes the same 36 features at signal time using only historical data
(up to and including current bar). Must match training feature logic exactly.
"""

import numpy as np

# Feature computation functions (copied from engineer_features.py for consistency)
def _rolling_mean(x, w):
    out = np.full(len(x), np.nan)
    cs = np.cumsum(np.insert(x, 0, 0))
    out[w-1:] = (cs[w:] - cs[:-w]) / w
    return out


def _rolling_std(x, w):
    out = np.full(len(x), np.nan)
    cs = np.cumsum(x)
    cs2 = np.cumsum(x**2)
    for i in range(w-1, len(x)):
        s = cs[i] - (cs[i-w] if i >= w else 0)
        s2 = cs2[i] - (cs2[i-w] if i >= w else 0)
        mean = s / w
        var = s2 / w - mean**2
        out[i] = np.sqrt(max(var, 0))
    return out


def _ema(x, span):
    alpha = 2 / (span + 1)
    ema = np.full(len(x), np.nan)
    ema[0] = x[0]
    for i in range(1, len(x)):
        ema[i] = alpha * x[i] + (1 - alpha) * ema[i-1]
    return ema


def compute_features_at_index(closes, highs, lows, volumes, idx):
    """Compute all 36 features at a specific bar index (no look-ahead)."""
    n = len(closes)
    if idx < 200 or idx >= n:
        return None  # not enough history

    # Use window of last 200 bars for computation
    c = closes[idx-199:idx+1]
    h = highs[idx-199:idx+1]
    l = lows[idx-199:idx+1]
    v = volumes[idx-199:idx+1]
    # Local index within window
    i = 199

    feat = {}

    # --- Momentum ---
    for w in [5, 10, 20, 50]:
        feat[f'ret_{w}'] = (c[i] - c[i-w]) / c[i-w]

    # RSI
    for period in [7, 14]:
        deltas = np.diff(c[i-period:i+1])
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = _ema(gains, period)[-1]
        avg_loss = _ema(losses, period)[-1]
        rs = avg_gain / (avg_loss + 1e-10)
        feat[f'rsi_{period}'] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = _ema(c, 12)
    ema26 = _ema(c, 26)
    macd_line = ema12 - ema26
    signal_line = _ema(macd_line, 9)
    feat['macd'] = macd_line[-1] / c[-1]
    feat['macd_signal'] = signal_line[-1] / c[-1]
    feat['macd_hist'] = (macd_line[-1] - signal_line[-1]) / c[-1]

    # --- Volatility ---
    for w in [10, 20, 50]:
        feat[f'vol_{w}'] = np.std(c[i-w+1:i+1]) / c[i]

    # ATR (14-period)
    tr = np.zeros(len(c))
    tr[1:] = np.maximum(h[1:] - l[1:],
                         np.maximum(np.abs(h[1:] - c[:-1]),
                                    np.abs(l[1:] - c[:-1])))
    atr = _rolling_mean(tr, 14)[-1]
    feat['atr_14'] = atr / c[-1]

    # Bollinger Band position and width
    ma20 = np.mean(c[-20:])
    std20 = np.std(c[-20:])
    if std20 > 0 and ma20 > 0:
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        feat['bb_pos'] = (c[-1] - lower) / (upper - lower)
        feat['bb_width'] = (upper - lower) / ma20
    else:
        feat['bb_pos'] = 0.5
        feat['bb_width'] = 0

    # Range ratio and close position
    hl = h[-1] - l[-1]
    feat['range_ratio'] = hl / c[-1] if c[-1] > 0 else 0
    feat['close_position'] = (c[-1] - l[-1]) / hl if hl > 0 else 0.5

    # --- Volume ---
    for w in [10, 20, 50]:
        ma = np.mean(v[-w:])
        feat[f'vol_ratio_{w}'] = v[-1] / ma if ma > 0 else 1

    ma50 = np.mean(v[-50:])
    feat['vol_spike'] = v[-1] / ma50 if ma50 > 0 else 1

    # --- Regime ---
    for w in [20, 50, 100, 200]:
        ma = np.mean(c[-w:])
        feat[f'price_vs_ma{w}'] = (c[-1] - ma) / ma if ma > 0 else 0

    # MA crosses
    ma20v = np.mean(c[-20:])
    ma50v = np.mean(c[-50:])
    ma100v = np.mean(c[-100:])
    feat['ma50_ma20_cross'] = (ma20v - ma50v) / ma50v if ma50v > 0 else 0
    feat['ma100_ma50_cross'] = (ma50v - ma100v) / ma100v if ma100v > 0 else 0

    # Trend slope (MA50 change over 20 bars)
    ma50_vals = [np.mean(c[j-50:j]) for j in range(len(c)-20, len(c))]
    if len(ma50_vals) > 1 and ma50_vals[0] > 0:
        feat['trend_slope'] = (ma50_vals[-1] - ma50_vals[0]) / ma50_vals[0]
    else:
        feat['trend_slope'] = 0

    # --- Microstructure ---
    # Consecutive direction
    consec = 0
    if i > 0:
        sign = np.sign(c[i] - c[i-1])
        for j in range(i, max(0, i-20), -1):
            if j > 0 and np.sign(c[j] - c[j-1]) == sign:
                consec += 1
            else:
                break
        feat['consec_direction'] = consec * sign
    else:
        feat['consec_direction'] = 0

    # HH/LL streaks (5-bar)
    hh5 = sum(1 for j in range(i-4, i+1) if h[j] > h[j-1])
    ll5 = sum(1 for j in range(i-4, i+1) if l[j] < l[j-1])
    feat['hh_streak_5'] = hh5
    feat['ll_streak_5'] = ll5

    # Momentum acceleration
    d1 = c[-1] - c[-6]
    d2 = c[-6] - c[-11]
    feat['momentum_accel'] = (d1 - d2) / c[-1]

    # Time features (idx is absolute bar index)
    feat['hour_sin'] = np.sin(2 * np.pi * (idx % 1440) / 1440)
    feat['hour_cos'] = np.cos(2 * np.pi * (idx % 1440) / 1440)
    feat['dow_sin'] = np.sin(2 * np.pi * ((idx // 1440) % 7) / 7)
    feat['dow_cos'] = np.cos(2 * np.pi * ((idx // 1440) % 7) / 7)

    # Orderbook microstructure features (NaN for historical data - not available for training)
    feat['spread_bps'] = np.nan
    feat['imb_1'] = np.nan
    feat['imb_5'] = np.nan
    feat['depth_5'] = np.nan
    feat['depth_10'] = np.nan
    feat['vwap_mid_5'] = np.nan
    feat['kyle_lambda_5'] = np.nan
    feat['spread_roll_10'] = np.nan
    feat['imb_5_roll_20'] = np.nan
    feat['spread_bps_dup'] = np.nan

    return feat


# Expected feature order (must match training)
FEATURE_ORDER = [
    'ret_5', 'ret_10', 'ret_20', 'ret_50',
    'rsi_7', 'rsi_14',
    'macd', 'macd_signal', 'macd_hist',
    'vol_10', 'vol_20', 'vol_50',
    'atr_14', 'bb_pos', 'bb_width',
    'range_ratio', 'close_position',
    'vol_ratio_10', 'vol_ratio_20', 'vol_ratio_50', 'vol_spike',
    'price_vs_ma20', 'price_vs_ma50', 'price_vs_ma100', 'price_vs_ma200',
    'ma50_ma20_cross', 'ma100_ma50_cross', 'trend_slope',
    'consec_direction', 'hh_streak_5', 'll_streak_5', 'momentum_accel',
    'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
]


def compute_orderbook_features_at_index(ob_history, idx):
    """Compute 10 orderbook microstructure features at bar index idx.

    NOTE: Currently returns NaN for all features since historical orderbook
    data is not available for training. This infrastructure is kept for
    future use when historical orderbook data becomes available.

    Args:
        ob_history: List of orderbook snapshots (each with 'bookTicker' and 'depth')
        idx: Bar index (0-based)

    Returns:
        dict of 10 microstructure features (all NaN for now) or None if insufficient data
    """
    # Orderbook features are not available for historical training data
    # Return NaN for all 10 features to maintain feature schema compatibility
    return {
        'spread_bps': np.nan,
        'imb_1': np.nan,
        'imb_5': np.nan,
        'depth_5': np.nan,
        'depth_10': np.nan,
        'vwap_mid_5': np.nan,
        'kyle_lambda_5': np.nan,
        'spread_roll_10': np.nan,
        'imb_5_roll_20': np.nan,
        'spread_bps': np.nan,  # duplicate name kept for compatibility
    }


# Expected feature order (must match training)
FEATURE_ORDER = [
    'ret_5', 'ret_10', 'ret_20', 'ret_50',
    'rsi_7', 'rsi_14',
    'macd', 'macd_signal', 'macd_hist',
    'vol_10', 'vol_20', 'vol_50',
    'atr_14', 'bb_pos', 'bb_width',
    'range_ratio', 'close_position',
    'vol_ratio_10', 'vol_ratio_20', 'vol_ratio_50', 'vol_spike',
    'price_vs_ma20', 'price_vs_ma50', 'price_vs_ma100', 'price_vs_ma200',
    'ma50_ma20_cross', 'ma100_ma50_cross', 'trend_slope',
    'consec_direction', 'hh_streak_5', 'll_streak_5', 'momentum_accel',
    'hour_sin', 'hour_cos', 'dow_sin', 'dow_cos',
    # Orderbook microstructure features (10) - NaN for training, live at inference
    'spread_bps', 'imb_1', 'imb_5', 'depth_5', 'depth_10',
    'vwap_mid_5', 'kyle_lambda_5', 'spread_roll_10', 'imb_5_roll_20',
    'spread_bps_dup',  # duplicate name kept for compatibility
]


def features_to_array(feat_dict):
    """Convert feature dict to ordered array for model prediction."""
    if feat_dict is None:
        return None
    return np.array([feat_dict.get(f, np.nan) for f in FEATURE_ORDER], dtype=np.float32).reshape(1, -1)