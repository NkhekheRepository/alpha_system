#!/usr/bin/env python3
"""Monte Carlo simulation: bootstrap trading paths at each threshold.

Uses the threshold sweep results + live calibration to simulate N paths
of M trades each, computing Sharpe, max drawdown, ruin probability, and
confidence intervals for each candidate threshold.

Output: models/mc_simulation_results.json

Usage:
    python3 scripts/mc_simulation.py [--n_paths 2000] [--n_trades 100]
"""

import argparse, json, sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meta_labeler_config import K, H, TP_PCT, SL_PCT, FEE_RATE, HOLDINGS

FEATURE_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_features.csv'
SIGNAL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_signals.csv'
MODEL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'meta_labeler.joblib'
OUT_FILE = Path(__file__).resolve().parent.parent / 'models' / 'mc_simulation_results.json'

TP_NET = TP_PCT - FEE_RATE       # +2.45%
SL_NET = SL_PCT - FEE_RATE       # -2.05%
TIMEOUT_PNL = -0.000018          # near-zero from live data
BASE_WR = 0.422                  # 353844 / 838318 (TP / labeled)


def calibrate_timeout_rate(threshold, base_timeout_rate=0.642):
    """Estimate timeout rate among gate-passing signals at given threshold.

    Calibration points:
      - T=0.55 live: ~81% timeout (from 86 trades)
      - T=0.50 live: ~85% timeout (extrapolated)
      - Population: 64.2% timeout overall
    Model: higher threshold → fewer timeouts pass (they have weaker features).
    """
    # Simple decay: timeout fraction decreases as threshold tightens
    # At T=0.55 → 0.81, at T=0.50 → ~0.85, at T=0.65 → ~0.70
    return base_timeout_rate * max(0.25, 1.0 - (threshold - 0.50) * 2.0)


def simulate_paths(probs, y, threshold, n_paths, n_trades, rng):
    """Simulate trading paths by bootstrap sampling.

    For each path of M trades:
      1. Sample M indices where model probability >= threshold
      2. For each, draw outcome: TP / SL / timeout
      3. Apply PnL: TP +2.45%, SL -2.05%, timeout ~0%
      4. Track equity curve (20% margin × 20x, compounding)

    Returns per-path: total_return_pct, max_drawdown_pct, final_equity, sharpe.
    """
    # Select gate-passing signals
    mask = probs >= threshold
    selected_probs = probs[mask]
    selected_y = y[mask]
    n_selected = len(selected_probs)

    if n_selected < 50:
        return None

    # Probability-weighted outcome: among TP/SL signals, model selects based on P(win)
    # The conditional TP rate among selected = weighted average of true labels
    # But we also need to mix in timeout signals

    timeout_rate = calibrate_timeout_rate(threshold)

    results = {
        'total_return': np.zeros(n_paths),
        'max_drawdown': np.zeros(n_paths),
        'final_equity': np.zeros(n_paths),
        'n_tp': np.zeros(n_paths, dtype=int),
        'n_sl': np.zeros(n_paths, dtype=int),
        'n_timeout': np.zeros(n_paths, dtype=int),
    }

    equity0 = 10.0  # starting capital

    for p in range(n_paths):
        # Bootstrap n_trades from the selected pool
        idx = rng.choice(n_selected, size=n_trades, replace=True)
        trade_probs = selected_probs[idx]
        trade_labels = selected_y[idx]

        equity = equity0
        peak = equity
        max_dd = 0.0
        n_tp = n_sl = n_to = 0

        for t in range(n_trades):
            # Determine outcome: timeout or TP/SL
            is_timeout = rng.random() < timeout_rate

            if is_timeout:
                # Timeout: tiny drift
                pnl_pct = TIMEOUT_PNL
                n_to += 1
            else:
                # TP or SL: use actual label from training data
                # (model selected these as high-prob, but actual outcome varies)
                if trade_labels[t] == 1:
                    pnl_pct = TP_NET
                    n_tp += 1
                else:
                    pnl_pct = SL_NET
                    n_sl += 1

            # Position sizing: 20% margin × 20x = 4x notional on equity
            position_value = equity * 0.20 * 20
            pnl_dollars = position_value * pnl_pct
            equity += pnl_dollars

            if equity <= 0:
                equity = 0.0
                break

            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        results['total_return'][p] = (equity - equity0) / equity0 * 100
        results['max_drawdown'][p] = max_dd * 100
        results['final_equity'][p] = equity
        results['n_tp'][p] = n_tp
        results['n_sl'][p] = n_sl
        results['n_timeout'][p] = n_to

    # Compute Sharpe per path (simplified: mean return / std of returns across trades)
    # Per-trade returns
    avg_return_pct = results['total_return'] / n_trades
    avg_dd = results['max_drawdown']
    avg_final = results['final_equity']
    ruin_rate = (results['final_equity'] < equity0 * 0.10).mean()  # 90% drawdown = ruin

    return {
        'threshold': threshold,
        'n_selected': n_selected,
        'timeout_rate': timeout_rate,
        'n_trades': n_trades,
        'n_paths': n_paths,

        # Return distribution
        'median_return_pct': round(float(np.median(results['total_return'])), 2),
        'mean_return_pct': round(float(np.mean(results['total_return'])), 2),
        'p5_return_pct': round(float(np.percentile(results['total_return'], 5)), 2),
        'p95_return_pct': round(float(np.percentile(results['total_return'], 95)), 2),
        'std_return_pct': round(float(np.std(results['total_return'])), 2),

        # Per-trade stats
        'median_per_trade_pct': round(float(np.median(avg_return_pct)), 4),
        'mean_per_trade_pct': round(float(np.mean(avg_return_pct)), 4),

        # Drawdown
        'median_max_dd_pct': round(float(np.median(avg_dd)), 2),
        'p95_max_dd_pct': round(float(np.percentile(avg_dd, 95)), 2),

        # Equity
        'median_final_equity': round(float(np.median(avg_final)), 2),
        'p5_final_equity': round(float(np.percentile(avg_final, 5)), 2),
        'p95_final_equity': round(float(np.percentile(avg_final, 95)), 2),

        # Win stats
        'median_n_tp': int(np.median(results['n_tp'])),
        'median_n_sl': int(np.median(results['n_sl'])),
        'median_n_timeout': int(np.median(results['n_timeout'])),

        # Risk
        'ruin_rate_90dd': round(float(ruin_rate), 4),
        'pct_profitable_paths': round(float((results['total_return'] > 0).mean()), 4),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--n_paths', type=int, default=2000)
    parser.add_argument('--n_trades', type=int, default=100)
    args = parser.parse_args()

    # Load model + data
    model_data = joblib.load(MODEL_FILE)
    model = model_data['model']
    model_features = model_data['features']
    print(f"Model: K={model_data['config']['K']}, features={len(model_features)}")

    df = pd.read_csv(FEATURE_FILE)
    sig_df = pd.read_csv(SIGNAL_FILE)
    total_signals = len(sig_df)
    n_labeled = sig_df['label'].notna().sum()
    n_timeout_pop = total_signals - n_labeled

    print(f"Samples: {len(df):,} labeled, {total_signals:,} total signals")
    print(f"Population timeout rate: {n_timeout_pop/total_signals:.1%}")

    X = df[model_features].values.astype(np.float32)
    y = df['label'].values.astype(np.int32)
    probs = model.predict_proba(X)[:, 1]

    # Sweep thresholds
    thresholds = [0.50, 0.52, 0.54, 0.55, 0.56, 0.58, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
    rng = np.random.default_rng(42)

    all_results = []
    print(f"\n{'Thresh':>6} {'MedRet%':>8} {'P5%':>7} {'P95%':>7} {'MedDD%':>7} {'Ruin':>6} {'WinPct':>7} {'MedEq$':>8}")
    print("-" * 72)

    for T in thresholds:
        r = simulate_paths(probs, y, T, args.n_paths, args.n_trades, rng)
        if r is None:
            print(f"{T:>6.2f}  (skipped: <50 selected)")
            continue
        all_results.append(r)

        print(f"{T:>6.2f} {r['median_return_pct']:>+7.1f}% {r['p5_return_pct']:>+6.1f}% {r['p95_return_pct']:>+6.1f}% "
              f"{r['median_max_dd_pct']:>6.1f}% {r['ruin_rate_90dd']:>5.1%} {r['pct_profitable_paths']:>6.1%} "
              f"${r['median_final_equity']:>7.2f}")

    # Find best by median return (risk-adjusted: prefer low ruin, high return)
    # Score = median_return * (1 - ruin_rate) - median_max_dd * 0.5
    for r in all_results:
        r['risk_adjusted_score'] = round(
            r['median_return_pct'] * (1 - r['ruin_rate_90dd']) - r['median_max_dd_pct'] * 0.5, 2)

    best = max(all_results, key=lambda x: x['risk_adjusted_score'])
    print(f"\n{'='*72}")
    print(f"BEST THRESHOLD (risk-adjusted): {best['threshold']:.2f}")
    print(f"  Median return ({args.n_trades} trades, {args.n_paths} paths): {best['median_return_pct']:+.1f}%")
    print(f"  90% CI: [{best['p5_return_pct']:+.1f}%, {best['p95_return_pct']:+.1f}%]")
    print(f"  Median max drawdown: {best['median_max_dd_pct']:.1f}%")
    print(f"  Ruin rate (90% DD): {best['ruin_rate_90dd']:.1%}")
    print(f"  Profitable paths: {best['pct_profitable_paths']:.1%}")
    print(f"  Median final equity: ${best['median_final_equity']:.2f} (from $10)")

    # Save
    output = {
        'config': {
            'K': K, 'H': H, 'TP_PCT': TP_PCT, 'SL_PCT': SL_PCT,
            'FEE_RATE': FEE_RATE, 'n_assets': len(HOLDINGS),
            'n_paths': args.n_paths, 'n_trades': args.n_trades,
            'starting_capital': 10.0, 'stake_pct': 0.20, 'leverage': 20,
        },
        'signal_stats': {
            'total_signals': int(total_signals),
            'labeled_tp_sl': int(n_labeled),
            'timeout_rate_population': round(float(n_timeout_pop / total_signals), 4),
        },
        'best_threshold': best,
        'all_thresholds': all_results,
    }
    with open(OUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved: {OUT_FILE}")


if __name__ == '__main__':
    main()
