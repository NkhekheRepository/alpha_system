#!/usr/bin/env python3
"""Quick backtest of meta-labeler on historical data.

Simulates Alpha 3 with meta-labeler filter on the 6 months of data.
"""

import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from meta_labeler_config import K, H, TP_PCT, SL_PCT, FEE_RATE, HOLDINGS

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meta_features import compute_features_at_index as compute_meta_features, features_to_array, FEATURE_ORDER


def main():
    # Load model
    model_data = joblib.load('/home/nkhekhe/alpha_system/models/meta_labeler.joblib')
    model = model_data['model']
    threshold = model_data['threshold']
    print(f"Model: threshold={threshold}")

    # Load klines
    kline_dir = Path('/home/nkhekhe/alpha_system/models/kline_data')
    klines = {}
    for sym in HOLDINGS:
        df = pd.read_csv(kline_dir / f"{sym}_1m.csv").sort_values('open_time')
        klines[sym] = {
            'closes': df['close'].values,
            'highs': df['high'].values,
            'lows': df['low'].values,
            'volumes': df['volume'].values,
        }
    print(f"Loaded klines for {len(klines)} symbols")

    # Load labels
    labels_df = pd.read_csv('/home/nkhekhe/alpha_system/models/labeled_signals.csv')
    labeled = labels_df.dropna(subset=['label']).copy()
    print(f"Labeled signals: {len(labeled):,}")

    total_trades = 0
    total_wins = 0
    total_filtered = 0

    for sym in HOLDINGS:
        sym_labels = labeled[labeled['symbol'] == sym].copy()
        k = klines[sym]
        print(f"\n  {sym}: {len(sym_labels):,} signals...", end='')

        wins = 0
        trades = 0
        filtered = 0

        for _, row in sym_labels.iterrows():
            idx = int(row['time_idx'])
            label = row['label']

            # Compute features
            feat = compute_meta_features(k['closes'], k['highs'], k['lows'], k['volumes'], idx)
            if feat is None:
                continue
            feat_arr = features_to_array(feat)
            if feat_arr is None or np.any(np.isnan(feat_arr)):
                continue

            # Meta-labeler prediction
            prob = model.predict_proba(feat_arr)[0, 1]

            if prob >= threshold:
                trades += 1
                if label == 1:
                    wins += 1
            else:
                filtered += 1

        wr = 100 * wins / trades if trades > 0 else 0
        raw_wr = 100 * (sym_labels['label'] == 1).sum() / len(sym_labels)
        print(f" trades={trades}, wins={wins}, WR={wr:.1f}% (raw={raw_wr:.1f}%), filtered={filtered}")

        total_trades += trades
        total_wins += wins
        total_filtered += filtered

    overall_wr = 100 * total_wins / total_trades if total_trades > 0 else 0
    raw_labels = labeled[labeled['symbol'].isin(HOLDINGS)]
    raw_wr = 100 * (raw_labels['label'] == 1).sum() / len(raw_labels)

    print(f"\n=== OVERALL ===")
    print(f"  Raw WR: {raw_wr:.1f}%")
    print(f"  Filtered WR: {overall_wr:.1f}% (+{overall_wr - raw_wr:.1f}pp)")
    print(f"  Trades: {total_trades:,} (selected {100*total_trades/len(raw_labels):.1f}%)")
    print(f"  Filtered out: {total_filtered:,}")


if __name__ == '__main__':
    main()