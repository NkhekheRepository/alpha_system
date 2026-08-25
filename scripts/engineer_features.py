#!/usr/bin/env python3
"""Compute features at each LABELED signal point for meta-labeler training.

All features use only data up to and including the signal bar (no look-ahead).
Output: models/labeled_features.csv

Usage:
    python3 scripts/engineer_features.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meta_labeler_config import K, H, TP_PCT, SL_PCT, FEE_RATE, HOLDINGS

KLINE_DIR = Path(__file__).resolve().parent.parent / 'models' / 'kline_data'
LABEL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_signals.csv'
OUT_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_features.csv'


def _rolling_mean(x, w):
    """Vectorized rolling mean with NaN for insufficient data."""
    out = np.full(len(x), np.nan)
    cs = np.cumsum(np.insert(x, 0, 0))
    out[w-1:] = (cs[w:] - cs[:-w]) / w
    return out


def _rolling_std(x, w):
    """Vectorized rolling std via cumulative sums."""
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
    """Exponential moving average."""
    return pd.Series(x).ewm(span=span, min_periods=span).mean().values


def compute_features_at_indices(closes, highs, lows, volumes, indices):
    """Compute features ONLY at specific bar indices (vectorized per feature)."""
    n = len(closes)
    feat = {}
    idx_arr = np.array(indices, dtype=int)

    # --- Momentum ---
    for w in [5, 10, 20, 50]:
        ret = np.full(n, np.nan)
        ret[w:] = (closes[w:] - closes[:-w]) / closes[:-w]
        feat[f'ret_{w}'] = ret[idx_arr]

    # RSI
    for period in [7, 14]:
        rsi = np.full(n, np.nan)
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = _ema(gains, period)[period:]
        avg_loss = _ema(losses, period)[period:]
        rs = avg_gain / (avg_loss + 1e-10)
        rsi_vals = 100 - (100 / (1 + rs))
        rsi[period+1:] = rsi_vals
        feat[f'rsi_{period}'] = rsi[idx_arr]

    # MACD
    if n > 26:
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        macd_line = ema12 - ema26
        signal_line = _ema(macd_line, 9)
        macd = np.full(n, np.nan)
        macd[26:] = macd_line[26:] / closes[26:]
        feat['macd'] = macd[idx_arr]
        macd_sig = np.full(n, np.nan)
        macd_sig[35:] = signal_line[35:] / closes[35:]
        feat['macd_signal'] = macd_sig[idx_arr]
        macd_hist = np.full(n, np.nan)
        macd_hist[35:] = (macd_line[35:] - signal_line[35:]) / closes[35:]
        feat['macd_hist'] = macd_hist[idx_arr]

    # --- Volatility ---
    for w in [10, 20, 50]:
        vol = np.full(n, np.nan)
        for i in range(w-1, n):
            vol[i] = np.std(closes[i-w+1:i+1]) / closes[i]
        feat[f'vol_{w}'] = vol[idx_arr]

    # ATR (14-period)
    tr = np.zeros(n)
    tr[1:] = np.maximum(highs[1:] - lows[1:],
                         np.maximum(np.abs(highs[1:] - closes[:-1]),
                                    np.abs(lows[1:] - closes[:-1])))
    atr = _rolling_mean(tr, 14)
    atr_norm = np.full(n, np.nan)
    mask = closes > 0
    atr_norm[mask] = atr[mask] / closes[mask]
    feat['atr_14'] = atr_norm[idx_arr]

    # Bollinger Band position and width
    bb_pos = np.full(n, np.nan)
    bb_width = np.full(n, np.nan)
    ma20 = _rolling_mean(closes, 20)
    std20 = _rolling_std(closes, 20)
    for i in range(19, n):
        if std20[i] > 0 and ma20[i] > 0:
            upper = ma20[i] + 2 * std20[i]
            lower = ma20[i] - 2 * std20[i]
            bb_pos[i] = (closes[i] - lower) / (upper - lower)
            bb_width[i] = (upper - lower) / ma20[i]
    feat['bb_pos'] = bb_pos[idx_arr]
    feat['bb_width'] = bb_width[idx_arr]

    # Range ratio and close position
    range_ratio = np.full(n, np.nan)
    close_pos = np.full(n, np.nan)
    hl = highs - lows
    mask2 = hl > 0
    range_ratio[mask2] = hl[mask2] / closes[mask2]
    close_pos[mask2] = (closes[mask2] - lows[mask2]) / hl[mask2]
    feat['range_ratio'] = range_ratio[idx_arr]
    feat['close_position'] = close_pos[idx_arr]

    # --- Volume ---
    for w in [10, 20, 50]:
        vol_ma = _rolling_mean(volumes, w)
        vr = np.full(n, np.nan)
        mask3 = vol_ma > 0
        vr[mask3] = volumes[mask3] / vol_ma[mask3]
        feat[f'vol_ratio_{w}'] = vr[idx_arr]

    vol_ma50 = _rolling_mean(volumes, 50)
    spike = np.full(n, np.nan)
    mask4 = vol_ma50 > 0
    spike[mask4] = volumes[mask4] / vol_ma50[mask4]
    feat['vol_spike'] = spike[idx_arr]

    # --- Regime ---
    for w in [20, 50, 100, 200]:
        ma = _rolling_mean(closes, w)
        pvm = np.full(n, np.nan)
        mask5 = ma > 0
        pvm[mask5] = (closes[mask5] - ma[mask5]) / ma[mask5]
        feat[f'price_vs_ma{w}'] = pvm[idx_arr]

    # MA crosses
    ma20v = _rolling_mean(closes, 20)
    ma50v = _rolling_mean(closes, 50)
    ma100v = _rolling_mean(closes, 100)
    cross_50_20 = np.full(n, np.nan)
    mask6 = ma50v > 0
    cross_50_20[mask6] = (ma20v[mask6] - ma50v[mask6]) / ma50v[mask6]
    feat['ma50_ma20_cross'] = cross_50_20[idx_arr]
    cross_100_50 = np.full(n, np.nan)
    mask7 = ma100v > 0
    cross_100_50[mask7] = (ma50v[mask7] - ma100v[mask7]) / ma100v[mask7]
    feat['ma100_ma50_cross'] = cross_100_50[idx_arr]

    # Trend slope (MA50 change over 20 bars)
    trend_slope = np.full(n, np.nan)
    for i in range(69, n):
        ma_a = ma50v[i]
        ma_b = ma50v[i-20]
        if ma_b > 0:
            trend_slope[i] = (ma_a - ma_b) / ma_b
    feat['trend_slope'] = trend_slope[idx_arr]

    # --- Microstructure ---
    # Consecutive direction
    consec = np.zeros(n)
    for i in range(1, n):
        sign = np.sign(closes[i] - closes[i-1])
        if sign == consec[i-1] and sign != 0:
            consec[i] = consec[i-1] + sign
        else:
            consec[i] = sign
    feat['consec_direction'] = consec[idx_arr]

    # HH/LL streaks (5-bar)
    hh_bar = np.zeros(n, dtype=float)
    ll_bar = np.zeros(n, dtype=float)
    hh_bar[1:] = (highs[1:] > highs[:-1]).astype(float)
    ll_bar[1:] = (lows[1:] < lows[:-1]).astype(float)
    cs_hh = np.cumsum(hh_bar)
    cs_ll = np.cumsum(ll_bar)
    hh5 = np.full(n, np.nan)
    ll5 = np.full(n, np.nan)
    hh5[4:] = cs_hh[4:] - np.concatenate([[0], cs_hh[:-5]])
    ll5[4:] = cs_ll[4:] - np.concatenate([[0], cs_ll[:-5]])
    feat['hh_streak_5'] = hh5[idx_arr]
    feat['ll_streak_5'] = ll5[idx_arr]

    # Momentum acceleration
    accel = np.full(n, np.nan)
    for i in range(10, n):
        d1 = closes[i] - closes[i-5]
        d2 = closes[i-5] - closes[i-10]
        accel[i] = (d1 - d2) / closes[i]
    feat['momentum_accel'] = accel[idx_arr]

    # Time features
    n_idx = len(idx_arr)
    feat['hour_sin'] = np.sin(2 * np.pi * (idx_arr % 1440) / 1440)
    feat['hour_cos'] = np.cos(2 * np.pi * (idx_arr % 1440) / 1440)
    feat['dow_sin'] = np.sin(2 * np.pi * ((idx_arr // 1440) % 7) / 7)
    feat['dow_cos'] = np.cos(2 * np.pi * ((idx_arr // 1440) % 7) / 7)

    return feat


def main():
    labels_df = pd.read_csv(LABEL_FILE)
    print(f"Loaded {len(labels_df):,} total signals")

    # Filter to ONLY labeled signals (non-NaN labels)
    labeled = labels_df.dropna(subset=['label']).copy()
    print(f"  Labeled (TP/SL): {len(labeled):,} ({100*len(labeled)/len(labels_df):.1f}%)")

    all_klines = {}
    for sym in HOLDINGS:
        csv_path = KLINE_DIR / f"{sym}_1m.csv"
        if csv_path.exists():
            df = pd.read_csv(csv_path).sort_values('open_time').reset_index(drop=True)
            all_klines[sym] = {
                'closes': df['close'].values.astype(np.float64),
                'highs': df['high'].values.astype(np.float64),
                'lows': df['low'].values.astype(np.float64),
                'volumes': df['volume'].values.astype(np.float64),
            }
    print(f"Loaded klines for {len(all_klines)} symbols")

    all_dfs = []
    for sym in HOLDINGS:
        if sym not in all_klines:
            continue
        k = all_klines[sym]
        sym_labels = labeled[labeled['symbol'] == sym].copy()
        time_idxs = sym_labels['time_idx'].values.astype(int)
        print(f"  {sym}: computing {len(time_idxs):,} features...", end='', flush=True)

        feat = compute_features_at_indices(k['closes'], k['highs'], k['lows'], k['volumes'], time_idxs)

        feat_names = list(feat.keys())
        feat_matrix = np.column_stack([feat[f] for f in feat_names])
        feat_df = pd.DataFrame(feat_matrix, columns=feat_names)

        combined = pd.concat([sym_labels.reset_index(drop=True), feat_df], axis=1)
        all_dfs.append(combined)

        coverage = feat_df.notna().all(axis=1).mean() * 100
        print(f" {len(feat_names)} features, {coverage:.0f}% coverage")

    result = pd.concat(all_dfs, ignore_index=True)

    before = len(result)
    result = result.dropna()
    after = len(result)
    print(f"\nDropped {before - after:,} rows with NaN features ({after:,} remaining)")

    result.to_csv(OUT_FILE, index=False)
    print(f"Saved: {OUT_FILE}")
    feat_cols = [c for c in result.columns if c not in ['time_idx','symbol','direction','entry_price','label','barrier_bar']]
    print(f"Feature columns ({len(feat_cols)}): {feat_cols}")
    n_tp = int(result['label'].sum())
    n_sl = int((result['label'] == 0).sum())
    print(f"Labeled: {n_tp} TP / {n_sl} SL (WR {100*n_tp/(n_tp+n_sl):.1f}%)")


if __name__ == '__main__':
    main()