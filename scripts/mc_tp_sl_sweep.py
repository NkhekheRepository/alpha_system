#!/usr/bin/env python3
"""TP/SL Monte Carlo sweep using out-of-sample kline data.

Re-prices model-selected entries (T=0.56, deployed) against every (TP, SL) combo
via actual forward kline paths, then bootstrap 3000 paths x 100 trades.

Output: models/mc_tp_sl_sweep_056.json (T=0.56 = 4784 OOS entries)
"""

import json, sys
from pathlib import Path
from itertools import product

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meta_labeler_config import K, H, FEE_RATE, HOLDINGS

MODEL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'meta_labeler.joblib'
SIGNAL_FILE = Path(__file__).resolve().parent.parent / 'models' / 'labeled_features.csv'
KLINDIR = Path(__file__).resolve().parent.parent / 'models' / 'kline_data'
OUT_FILE = Path(__file__).resolve().parent.parent / 'models' / 'mc_tp_sl_sweep_056.json'

STAKING = 0.20
LEVERAGE = 20
NOTIONAL = STAKING * LEVERAGE
START_CAPITAL = 10.0
N_PATHS = 3000
N_TRADES = 100
THRESHOLD = 0.56  # deployed threshold — 4784 OOS entries vs 846 at 0.57

TP_GRID = [0.015, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05]
SL_GRID = [0.01, 0.015, 0.02, 0.025, 0.03]


def compute_exit_for_signal(row, kline_df, tp_pct, sl_pct):
    """Compute exit type and pnl for a single signal at given TP/SL.
    Returns (etype, pnl) where etype in {'TP', 'SL', 'TIMEOUT'}.
    """
    tidx = int(row['time_idx'])
    entry = float(row['entry_price'])
    direction = row['direction']

    if tidx >= len(kline_df) or tidx < 0:
        return 'TIMEOUT', 0.0

    avail = min(H, len(kline_df) - tidx - 1)
    if avail < 1:
        return 'TIMEOUT', 0.0

    window = kline_df.iloc[tidx+1 : tidx+avail+1]
    highs = window['high'].values.astype(np.float64)
    lows = window['low'].values.astype(np.float64)
    closes = window['close'].values.astype(np.float64)

    if direction == 'long':
        tp_target = entry * (1 + tp_pct)
        sl_target = entry * (1 - sl_pct)
        tp_hit = np.any(highs >= tp_target)
        sl_hit = np.any(lows <= sl_target)
    else:  # short
        tp_target = entry * (1 - tp_pct)
        sl_target = entry * (1 + sl_pct)
        tp_hit = np.any(lows <= tp_target)
        sl_hit = np.any(highs >= sl_target)

    if tp_hit and not sl_hit:
        return 'TP', tp_pct - FEE_RATE
    elif sl_hit and not tp_hit:
        return 'SL', -(sl_pct + FEE_RATE)
    elif tp_hit and sl_hit:
        if direction == 'long':
            tp_first = np.where(highs >= tp_target)[0][0]
            sl_first = np.where(lows <= sl_target)[0][0]
        else:
            tp_first = np.where(lows <= tp_target)[0][0]
            sl_first = np.where(highs >= sl_target)[0][0]
        if tp_first < sl_first:
            return 'TP', tp_pct - FEE_RATE
        else:
            return 'SL', -(sl_pct + FEE_RATE)
    else:
        # Timeout at close[H-1]
        close_at_H = closes[-1]
        if direction == 'long':
            return 'TIMEOUT', close_at_H / entry - 1
        else:
            return 'TIMEOUT', 1 - close_at_H / entry


def mc_bootstrap(exits, n_paths, n_trades, rng):
    """MC bootstrap: sample n_trades from exits for n_paths."""
    n = len(exits)
    if n < 10:
        return None

    sampled = rng.choice(n, size=(n_paths, n_trades), replace=True)
    pnls = exits[sampled]
    growth = 1 + NOTIONAL * pnls
    equity = np.cumprod(growth, axis=1) * START_CAPITAL
    final_eq = equity[:, -1]
    peak = np.maximum.accumulate(equity, axis=1)
    dd = (peak - equity) / peak
    max_dd = np.max(dd, axis=1)
    rets = (final_eq - START_CAPITAL) / START_CAPITAL * 100

    ruin = np.mean(final_eq < START_CAPITAL * 0.10)
    pct_profitable = np.mean(rets > 0)
    sharpe = np.mean(rets) / (np.std(rets) + 1e-10) * np.sqrt(24 * 60 / n_trades) if np.std(rets) > 0 else 0

    return {
        'median_return_pct': round(float(np.median(rets)), 2),
        'mean_return_pct': round(float(np.mean(rets)), 2),
        'p5_return_pct': round(float(np.percentile(rets, 5)), 2),
        'p95_return_pct': round(float(np.percentile(rets, 95)), 2),
        'median_max_dd_pct': round(float(np.median(max_dd)), 2),
        'p95_max_dd_pct': round(float(np.percentile(max_dd, 95)), 2),
        'median_final_equity': round(float(np.median(final_eq)), 2),
        'ruin_rate': round(float(ruin), 4),
        'pct_profitable_paths': round(float(pct_profitable), 4),
        'sharpe_est': round(float(sharpe), 2),
    }


def main():
    # Load model + selected signals
    model_data = joblib.load(MODEL_FILE)
    model = model_data['model']
    features = model_data['features']
    df = pd.read_csv(SIGNAL_FILE)
    X = df[features].values.astype(np.float32)
    probs = model.predict_proba(X)[:, 1]
    selected = df[probs >= THRESHOLD].copy()
    n_signals = len(selected)
    print(f"Selected signals at T={THRESHOLD}: {n_signals}")

    # Load klines
    kline_map = {}
    for sym in selected['symbol'].unique():
        k = pd.read_csv(KLINDIR / f'{sym}_1m.csv')
        kline_map[sym] = k

    # Compute exit mix per combo
    n_combos = len(TP_GRID) * len(SL_GRID)
    combo_exit_lists = [[] for _ in range(n_combos)]

    print(f"\nComputing exits for {n_signals} signals x {n_combos} combos...")
    for sig_idx in range(n_signals):
        sym = selected.iloc[sig_idx]['symbol']
        if sym not in kline_map:
            continue
        kline_df = kline_map[sym]
        row = selected.iloc[sig_idx]

        for ci in range(n_combos):
            tp_idx = ci // len(SL_GRID)
            sl_idx = ci % len(SL_GRID)
            tp_pct = TP_GRID[tp_idx]
            sl_pct = SL_GRID[sl_idx]
            etype, pnl = compute_exit_for_signal(row, kline_df, tp_pct, sl_pct)
            combo_exit_lists[ci].append((etype, pnl))

    # MC per combo
    all_results = {}
    sweep_grid = []
    rng = np.random.default_rng(42)

    print(f"\nRunning MC (3000 paths x 100 trades) for {n_combos} combos...")
    for ci in range(n_combos):
        tp_pct = TP_GRID[ci // len(SL_GRID)]
        sl_pct = SL_GRID[ci % len(SL_GRID)]
        key = f"TP{tp_pct*100:.1f}%_SL{sl_pct*100:.1f}%"

        exits = np.array([e[1] for e in combo_exit_lists[ci]])
        types = [e[0] for e in combo_exit_lists[ci]]
        n_tp = types.count('TP')
        n_sl = types.count('SL')
        n_to = types.count('TIMEOUT')
        tp_rate = n_tp / n_signals

        mc = mc_bootstrap(exits, N_PATHS, N_TRADES, rng)

        if mc:
            all_results[key] = {
                'tp_pct': tp_pct, 'sl_pct': sl_pct,
                'exit_mix': {'tp': n_tp, 'sl': n_sl, 'timeout': n_to},
                'tp_rate': round(tp_rate, 4),
                'mc': mc,
            }
            sweep_grid.append({
                'key': key, 'tp_pct': tp_pct, 'sl_pct': sl_pct,
                'median_return': mc['median_return_pct'],
                'p5_return': mc['p5_return_pct'],
                'p95_return': mc['p95_return_pct'],
                'median_dd': mc['median_max_dd_pct'],
                'ruin': mc['ruin_rate'],
                'pct_profitable': mc['pct_profitable_paths'],
                'median_equity': mc['median_final_equity'],
                'sharpe': mc['sharpe_est'],
                'tp_rate': tp_rate,
            })
            print(f"  {key}: ret={mc['median_return_pct']:+.1f}% "
                  f"[{mc['p5_return_pct']:+.1f}%, +{mc['p95_return_pct']:.1f}%] "
                  f"DD={mc['median_max_dd_pct']:.1f}% ruin={mc['ruin_rate']:.1%} "
                  f"win={mc['pct_profitable_paths']:.0%} sharpe={mc['sharpe_est']:.1f} "
                  f"mix=TP:{n_tp}/SL:{n_sl}/TO:{n_to}")

    # Risk-adjusted score
    for g in sweep_grid:
        g['score'] = round(g['median_return'] * (1 - g['ruin']) - g['median_dd'] * 0.5, 2)

    best = max(sweep_grid, key=lambda x: x['score'])
    print(f"\n{'='*80}")
    print(f"BEST TP/SL COMBO: {best['key']}")
    print(f"  Median return: {best['median_return']:+.1f}%")
    print(f"  90% CI: [{best['p5_return']:+.1f}%, +{best['p95_return']:.1f}%]")
    print(f"  Median max drawdown: {best['median_dd']:.1f}%")
    print(f"  Ruin rate: {best['ruin']:.1%}")
    print(f"  Profitable paths: {best['pct_profitable']:.0%}")
    print(f"  Median final equity: ${best['median_equity']:.2f}")
    print(f"  Sharpe: {best['sharpe']:.1f}")
    print(f"  Exit mix: {all_results[best['key']]['exit_mix']}")
    print(f"  TP rate: {best['tp_rate']:.1%}")

    output = {
        'config': {
            'threshold': THRESHOLD, 'K': K, 'H': H, 'FEE_RATE': FEE_RATE,
            'n_assets': len(HOLDINGS), 'staking': STAKING, 'leverage': LEVERAGE,
            'n_paths': N_PATHS, 'n_trades': N_TRADES,
            'starting_capital': START_CAPITAL,
        },
        'tp_grid': TP_GRID, 'sl_grid': SL_GRID,
        'best_combo': best,
        'full_sweep': all_results,
        'sweep_grid': sweep_grid,
    }
    with open(OUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nSaved: {OUT_FILE}")
    print(f"\nTop 5 by risk-adjusted score:")
    for r in sorted(sweep_grid, key=lambda x: x['score'], reverse=True)[:5]:
        print(f"  {r['key']}: ret={r['median_return']:+.1f}% DD={r['median_dd']:.1f}% "
              f"ruin={r['ruin']:.1%} win={r['pct_profitable']:.0%} "
              f"sharpe={r['sharpe']:.1f} tp_rate={r['tp_rate']:.0%} score={r['score']:.2f}")


if __name__ == '__main__':
    main()
