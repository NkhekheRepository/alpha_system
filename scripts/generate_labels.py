#!/usr/bin/env python3
"""Generate triple-barrier labels for meta-labeler training.

For each bar where momentum_direction(K=10) fires on 1m data:
  1. Walk forward H=75 bars
  2. Check if TP (+2%) or SL (-2%) is hit first
  3. Label: 1 = TP win, 0 = SL loss, NaN = timeout (dropped from training)

Output: models/labeled_signals.csv

Usage:
    python3 scripts/generate_labels.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meta_labeler_config import K, H, TP_PCT, SL_PCT, HOLDINGS

KLINE_DIR = Path(__file__).resolve().parent.parent / 'models' / 'kline_data'
OUT_DIR = Path(__file__).resolve().parent.parent / 'models'
OUT_FILE = OUT_DIR / 'labeled_signals.csv'


def compute_labels_vectorized(closes, highs, lows, k=K, h=H, tp=TP_PCT, sl=SL_PCT):
    """Vectorized triple-barrier labeling using numpy."""
    n = len(closes)

    # Momentum signal: direction at each bar
    # long if closes[i] > closes[i-k], else short
    direction = np.where(closes[k:] > closes[:n-k], 1, -1)  # 1=long, -1=short
    entry = closes[k:]  # entry price = close at signal bar

    # TP and SL prices (vectorized)
    tp_price = np.where(direction == 1, entry * (1.0 + tp), entry * (1.0 - tp))
    sl_price = np.where(direction == 1, entry * (1.0 + sl), entry * (1.0 + abs(sl)))

    n_signals = len(entry)
    labels = np.full(n_signals, np.nan)
    barrier_bars = np.full(n_signals, h, dtype=int)

    # For each signal, scan forward H bars for first barrier hit
    # Use numpy for speed on the inner loop
    for i in range(n_signals):
        bar_idx = i + k  # absolute bar index in the price arrays
        end_idx = min(bar_idx + h + 1, n)
        fwd_high = highs[bar_idx + 1:end_idx]
        fwd_low = lows[bar_idx + 1:end_idx]

        if len(fwd_high) == 0:
            continue

        d = direction[i]
        tp_p = tp_price[i]
        sl_p = sl_price[i]

        if d == 1:  # long
            tp_cross = np.argmax(fwd_high >= tp_p)
            sl_cross = np.argmax(fwd_low <= sl_p)
            tp_hit = fwd_high[tp_cross] >= tp_p if fwd_high[tp_cross] >= tp_p else False
            sl_hit = fwd_low[sl_cross] <= sl_p if fwd_low[sl_cross] <= sl_p else False
        else:  # short
            tp_cross = np.argmax(fwd_low <= tp_p)
            sl_cross = np.argmax(fwd_high >= sl_p)
            tp_hit = fwd_low[tp_cross] <= tp_p if fwd_low[tp_cross] <= tp_p else False
            sl_hit = fwd_high[sl_cross] >= sl_p if fwd_high[sl_cross] >= sl_p else False

        if tp_hit and sl_hit:
            if tp_cross < sl_cross:
                labels[i] = 1
                barrier_bars[i] = tp_cross + 1
            elif sl_cross < tp_cross:
                labels[i] = 0
                barrier_bars[i] = sl_cross + 1
            else:
                labels[i] = 1  # tie-break: favor TP
                barrier_bars[i] = tp_cross + 1
        elif tp_hit:
            labels[i] = 1
            barrier_bars[i] = tp_cross + 1
        elif sl_hit:
            labels[i] = 0
            barrier_bars[i] = sl_cross + 1
        # else: timeout, label stays NaN

    return labels, barrier_bars, direction, entry


def main():
    all_signals = []

    for sym in HOLDINGS:
        csv_path = KLINE_DIR / f"{sym}_1m.csv"
        if not csv_path.exists():
            print(f"  SKIP {sym}: {csv_path} not found")
            continue

        df = pd.read_csv(csv_path).sort_values('open_time').reset_index(drop=True)
        closes = df['close'].values.astype(np.float64)
        highs = df['high'].values.astype(np.float64)
        lows = df['low'].values.astype(np.float64)

        print(f"  {sym}: {len(df):,} bars", end='', flush=True)

        labels, barrier_bars, directions, entries = compute_labels_vectorized(closes, highs, lows)

        n_tp = int(np.nansum(labels == 1))
        n_sl = int(np.nansum(labels == 0))
        n_timeout = int(np.sum(np.isnan(labels)))
        n_signals = len(labels)
        wr = 100 * n_tp / (n_tp + n_sl) if (n_tp + n_sl) > 0 else 0

        print(f" -> {n_signals:,} signals ({n_tp} TP / {n_sl} SL / {n_timeout} timeout, WR {wr:.1f}%)")

        # Build time_idx from signal positions
        time_idx = np.arange(K, K + n_signals)

        sym_df = pd.DataFrame({
            'time_idx': time_idx,
            'symbol': sym,
            'direction': np.where(directions == 1, 'long', 'short'),
            'entry_price': entries,
            'label': labels,
            'barrier_bar': barrier_bars,
        })
        all_signals.append(sym_df)

    combined = pd.concat(all_signals, ignore_index=True)
    combined.to_csv(OUT_FILE, index=False)

    n_total = len(combined)
    n_labeled = int(combined['label'].notna().sum())
    n_tp = int((combined['label'] == 1).sum())
    n_sl = int((combined['label'] == 0).sum())
    wr = 100 * n_tp / n_labeled if n_labeled > 0 else 0

    print(f"\nTotal: {n_total:,} signals -> {n_labeled:,} labeled ({n_tp} TP / {n_sl} SL, WR {wr:.1f}%)")
    print(f"Timeouts dropped: {n_total - n_labeled:,}")
    print(f"Saved: {OUT_FILE}")


if __name__ == '__main__':
    main()
