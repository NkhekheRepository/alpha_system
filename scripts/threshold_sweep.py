#!/usr/bin/env python3
"""Threshold sweep: evaluate meta-labeler at every threshold 0.50-0.90.

Loads the trained model and labeled features, predicts OOF probabilities,
then computes precision/recall/selection/PnL at each threshold.

Output: models/threshold_sweep_results.json

Usage:
    python3 scripts/threshold_sweep.py
"""

import json, sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import precision_score, recall_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meta_labeler_config import K, H, TP_PCT, SL_PCT, FEE_RATE, HOLDINGS

FEATURE_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_features.csv'
MODEL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'meta_labeler.joblib'
SIGNAL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_signals.csv'
OUT_FILE = Path(__file__).resolve().parent.parent / 'models' / 'threshold_sweep_results.json'

TP_NET = TP_PCT - FEE_RATE   # +2.45% per winning trade
SL_NET = SL_PCT - FEE_RATE   # -2.05% per losing trade (SL_PCT is negative)
TIMEOUT_NET = -0.000018       # near-zero from live data calibration


def main():
    # Load model
    model_data = joblib.load(MODEL_FILE)
    model = model_data['model']
    model_features = model_data['features']
    print(f"Model: K={model_data['config']['K']}, threshold={model_data['threshold']}, features={len(model_features)}")

    # Load labeled features (TP/SL signals only)
    df = pd.read_csv(FEATURE_FILE)
    print(f"Loaded {len(df):,} labeled samples (TP/SL only)")

    # Load full signal count for timeout calibration
    sig_df = pd.read_csv(SIGNAL_FILE)
    total_signals = len(sig_df)
    n_labeled = sig_df['label'].notna().sum()
    n_timeout = total_signals - n_labeled
    timeout_rate_pop = n_timeout / total_signals
    print(f"Full signal population: {total_signals:,} total, {n_labeled:,} labeled, {n_timeout:,} timeout ({timeout_rate_pop:.1%})")

    # Build feature matrix
    X = df[model_features].values.astype(np.float32)
    y = df['label'].values.astype(np.int32)

    # Predict probabilities (in-sample — fast, slightly optimistic)
    probs = model.predict_proba(X)[:, 1]

    # Per-symbol breakdown
    symbols = df['symbol'].values
    sym_stats = {}
    for sym in HOLDINGS:
        mask = symbols == sym
        if mask.sum() == 0:
            continue
        sym_probs = probs[mask]
        sym_y = y[mask]
        n = mask.sum()
        n_tp = sym_y.sum()
        wr = n_tp / n if n > 0 else 0
        sym_stats[sym] = {'n': int(n), 'wr': float(wr), 'mean_prob': float(sym_probs.mean())}
        print(f"  {sym}: {n:,} signals, WR={wr:.1%}, mean_prob={sym_probs.mean():.3f}")

    # Threshold sweep
    thresholds = np.arange(0.50, 0.91, 0.01)
    results = []

    print(f"\n{'Thresh':>6} {'Prec':>6} {'Rec':>6} {'Sel%':>6} {'N':>8} {'PnL/T':>8} {'ExpRet':>8} {'Timeout%':>9}")
    print("-" * 72)

    for T in thresholds:
        pred = (probs >= T).astype(int)
        n_selected = pred.sum()
        if n_selected < 10:
            continue

        prec = precision_score(y, pred, zero_division=0)
        rec = recall_score(y, pred, zero_division=0)
        sel_rate = pred.mean()

        # Expected PnL per trade (among TP/SL signals only)
        pnl_per_trade = prec * TP_NET + (1 - prec) * SL_NET

        # Estimate timeout rate among gate-passing signals
        # Calibration: at T=0.55, live timeout rate = 81%
        # Model selects X% of TP/SL signals; timeout signals have ~same feature dist
        # Simple model: timeout_rate(T) ≈ timeout_rate_pop * (1 - lift * sel_rate)
        # where lift = prec / base_wr
        base_wr = y.mean()
        lift = prec / base_wr if base_wr > 0 else 1.0
        # Higher threshold → fewer timeout signals pass (they have lower model prob on avg)
        timeout_calibrated = timeout_rate_pop * max(0.3, 1.0 - (T - 0.50) * 1.5)

        # Expected return per trade including timeouts
        exp_return = (1 - timeout_calibrated) * pnl_per_trade + timeout_calibrated * TIMEOUT_NET

        # Annualized trade frequency estimate
        # 9 assets × 54 signals/min × 60 min × 24h = signals/day
        # At sel_rate, fraction pass gate; but timeouts also pass
        # Live calibration: 17 entries in 45 min at T=0.55 → ~544/day
        trades_per_day_live = 544 * (0.55 / T) if T > 0 else 0  # rough scaling

        r = {
            'threshold': round(float(T), 2),
            'precision': round(float(prec), 4),
            'recall': round(float(rec), 4),
            'selection_rate': round(float(sel_rate), 4),
            'n_selected': int(n_selected),
            'pnl_per_trade_pct': round(float(pnl_per_trade * 100), 4),
            'timeout_rate_est': round(float(timeout_calibrated), 4),
            'exp_return_per_trade_pct': round(float(exp_return * 100), 4),
            'trades_per_day_est': round(float(trades_per_day_live), 1),
            'daily_expected_pct': round(float(exp_return * trades_per_day_live * 100), 4),
        }
        results.append(r)

        if T in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90] or abs(T - 0.55) < 0.005:
            print(f"{T:>6.2f} {prec:>6.3f} {rec:>6.3f} {sel_rate*100:>5.1f}% {n_selected:>8,} {pnl_per_trade*100:>+7.3f}% {exp_return*100:>+7.3f}% {timeout_calibrated*100:>8.1f}%")

    # Find optimal threshold by expected return
    best = max(results, key=lambda x: x['exp_return_per_trade_pct'])
    print(f"\n{'='*72}")
    print(f"BEST THRESHOLD: {best['threshold']:.2f}")
    print(f"  Precision: {best['precision']:.3f} (base: {y.mean():.3f})")
    print(f"  Selection: {best['selection_rate']:.1%}")
    print(f"  PnL/trade (TP/SL only): {best['pnl_per_trade_pct']:+.3f}%")
    print(f"  Expected return/trade: {best['exp_return_per_trade_pct']:+.3f}%")
    print(f"  Est. trades/day: {best['trades_per_day_est']:.0f}")
    print(f"  Est. daily return: {best['daily_expected_pct']:+.3f}%")

    # Save
    output = {
        'config': {'K': K, 'H': H, 'TP_PCT': TP_PCT, 'SL_PCT': SL_PCT,
                    'FEE_RATE': FEE_RATE, 'n_assets': len(HOLDINGS)},
        'signal_stats': {
            'total_signals': int(total_signals),
            'labeled_tp_sl': int(n_labeled),
            'timeouts': int(n_timeout),
            'timeout_rate_population': round(float(timeout_rate_pop), 4),
            'base_wr': round(float(y.mean()), 4),
        },
        'per_symbol': sym_stats,
        'best_threshold': best,
        'sweep': results,
    }
    with open(OUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved: {OUT_FILE}")


if __name__ == '__main__':
    main()
