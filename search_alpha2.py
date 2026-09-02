#!/usr/bin/env python3
"""
Governed parameter search for Alpha 2 (NK-EXP-W8-1).

Pipeline (all gates from dry_data/alpha2_search_prereg.json):
  1. IS = full window minus OOS holdout (last 20% by time). CPCV-style 5-fold
     time segmentation of IS trades. No leakage: params selected on fold-median
     net Sharpe; OOS untouched until final stage.
  2. Selection gates: trades >= 100, barrier hit rate >= 5%, Sharpe > 0 in >= 60% folds.
  3. Top-5 candidates -> Monte Carlo robustness (stationary bootstrap + noise).
  4. Single OOS evaluation with exact engine -> GO/NO-GO.
"""

import json, sys, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_alpha2 as bt

DATA_DIR = Path('/home/nkhekhe/user_data/data/binance')
PREREG = json.load(open('/home/nkhekhe/alpha_system/dry_data/alpha2_search_prereg.json'))
ASSETS = {'BTCUSDT': 'BTC_USDT-5m.feather', 'ETHUSDT': 'ETH_USDT-5m.feather'}
FEE = 0.001
CAP = 100000.0

def build_combos(space):
    combos = []
    for k in space['momentum_k']:
        for tpsl in space['tp_sl']:
            for h in space['horizon_H']:
                for size in space['sizing_pct']:
                    for brk in space['breaker']:
                        combos.append({
                            'momentum_k': k, 'tp': tpsl, 'sl': tpsl,
                            'horizon': h, 'pos_pct': size,
                            'max_consec': brk,
                        })
    return combos

def fold_sharpe(trades, n_folds=5):
    """Segment trades into n time folds, return per-fold net Sharpe (trade-based ann)."""
    if len(trades) < 2:
        return [0.0] * n_folds
    times = pd.to_datetime([t['entry_time'] for t in trades])
    lo, hi = times.min(), times.max()
    folds = []
    for f in range(n_folds):
        a = lo + (hi - lo) * f / n_folds
        b = lo + (hi - lo) * (f + 1) / n_folds
        sub = [t for t, tm in zip(trades, times) if a <= tm < b]
        if len(sub) < 2:
            folds.append(0.0)
            continue
        rets = np.array([t['pnl_pct'] for t in sub])
        sd = rets.std(ddof=1)
        if sd == 0:
            folds.append(0.0)
            continue
        period_years = (b - a).total_seconds() / (365 * 24 * 3600)
        n_per_year = len(sub) / period_years if period_years > 0 else 0
        folds.append((rets.mean() / sd) * np.sqrt(n_per_year))
    return folds

def barrier_hit_rate(trades):
    if not trades:
        return 0.0
    hits = [t for t in trades if t['reason'] in ('TP', 'SL')]
    return len(hits) / len(trades)

def evaluate_combo(combo, symbols_data):
    """Run combo on IS for all symbols, combine trades, return metrics dict."""
    all_trades = []
    for sym, df in symbols_data.items():
        trades, end_eq, dd = bt.run_strategy(df, capital=CAP, fees=FEE, params=combo)
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t['entry_time'])
    folds = fold_sharpe(all_trades)
    n = len(all_trades)
    wins = sum(1 for t in all_trades if t['pnl_dollars'] > 0)
    total_pnl = sum(t['pnl_dollars'] for t in all_trades)
    return {
        'combo': combo,
        'trades': n,
        'win_rate': wins / n * 100 if n else 0.0,
        'barrier_hit_rate': barrier_hit_rate(all_trades) * 100,
        'fold_sharpes': folds,
        'median_sharpe': float(np.median(folds)),
        'pos_folds': sum(1 for s in folds if s > 0) / len(folds),
        'net_pnl': total_pnl,
        'net_return_pct': total_pnl / CAP * 100,
    }

def main():
    prereg = PREREG
    print("=" * 78)
    print(f"  ALPHA 2 GOVERNED SEARCH — {prereg['registration_id']}")
    print("=" * 78)

    # Load full data, split IS / OOS
    full = {}
    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA_DIR / fname)
        df.attrs['symbol'] = sym
        full[sym] = df
        print(f"  {sym}: {len(df):,} bars  {df['date'].iloc[0]} -> {df['date'].iloc[-1]}")

    # OOS = last 20% by timestamp
    cutoff = pd.Timestamp(full['BTCUSDT']['date'].iloc[-1]) - pd.Timedelta(
        days=0.2 * 365 * (full['BTCUSDT']['date'].iloc[-1] - full['BTCUSDT']['date'].iloc[0]).days / 365.0
    )
    cutoff = full['BTCUSDT']['date'].iloc[-1] - (full['BTCUSDT']['date'].iloc[-1] - full['BTCUSDT']['date'].iloc[0]) * 0.2
    is_data, oos_data = {}, {}
    for sym, df in full.items():
        mask = df['date'] < cutoff
        is_data[sym] = df[mask].reset_index(drop=True)
        oos_data[sym] = df[~mask].reset_index(drop=True)
    is_years = (is_data['BTCUSDT']['date'].iloc[-1] - is_data['BTCUSDT']['date'].iloc[0]).total_seconds() / (365 * 24 * 3600)
    print(f"  IS: {len(is_data['BTCUSDT']):,} bars ({is_years:.2f}y) | OOS: {len(oos_data['BTCUSDT']):,} bars (held out)")
    print(f"  Cutoff: {cutoff}")

    combos = build_combos(prereg['search_space'])
    print(f"\n  Searching {len(combos)} combos x {len(is_data)} symbols (IS only)...")
    t0 = time.time()

    results = []
    with ProcessPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(evaluate_combo, c, is_data) for c in combos]
        for i, f in enumerate(futures):
            results.append(f.result())
            if (i + 1) % 180 == 0:
                print(f"    {i+1}/{len(combos)} done ({time.time()-t0:.0f}s)")

    results.sort(key=lambda r: r['median_sharpe'], reverse=True)

    gates = prereg['selection_gates']
    passed = [r for r in results
              if r['trades'] >= gates['min_trades']
              and r['barrier_hit_rate'] >= gates['min_barrier_hit_rate'] * 100
              and r['pos_folds'] >= gates['min_folds_positive_sharpe']]
    print(f"\n  Done in {time.time()-t0:.0f}s. Combo results: {len(results)}")
    print(f"  Passing selection gates (trades>={gates['min_trades']}, barrier>={gates['min_barrier_hit_rate']*100:.0f}%, +Sharpe>={gates['min_folds_positive_sharpe']*100:.0f}% folds): {len(passed)}")

    print("\n  TOP 10 (by median fold Sharpe):")
    print(f"  {'k':>3} {'TPSL':>5} {'H':>4} {'size':>5} {'brk':>4} | {'trd':>5} {'WR%':>5} {'bar%':>5} {'medSh':>6} {'+fld':>5} {'PnL%':>7}")
    for r in results[:10]:
        c = r['combo']
        print(f"  {c['momentum_k']:>3} {c['tp']:>5.3f} {c['horizon']:>4} {c['pos_pct']:>5.3f} {c['max_consec']:>4} | "
              f"{r['trades']:>5} {r['win_rate']:>5.1f} {r['barrier_hit_rate']:>5.1f} {r['median_sharpe']:>6.2f} "
              f"{r['pos_folds']*100:>4.0f}% {r['net_return_pct']:>+7.2f}")

    if not passed:
        print("\n  >>> NO PARAMS PASS SELECTION GATES <<<")
        print("  Record as null result. OOS not consumed. No retuning (closed grid).")
        with open('/home/nkhekhe/alpha_system/dry_data/alpha2_search_results.json', 'w') as f:
            json.dump({'registration': prereg['registration_id'], 'passed': [], 'top': results[:10],
                       'verdict': 'NO-GO at selection stage'}, f, indent=2, default=str)
        return

    top5 = passed[:5]
    print(f"\n  TOP-5 PASSING (-> MC robustness stage):")
    for r in top5:
        c = r['combo']
        print(f"    k={c['momentum_k']} tp/sl={c['tp']} H={c['horizon']} size={c['pos_pct']} brk={c['max_consec']} | "
              f"trades={r['trades']} medSharpe={r['median_sharpe']:.2f} PnL={r['net_return_pct']:+.2f}%")

    # Save intermediate results
    with open('/home/nkhekhe/alpha_system/dry_data/alpha2_search_results.json', 'w') as f:
        json.dump({
            'registration': prereg['registration_id'],
            'cutoff': str(cutoff),
            'top5': top5, 'top10': results[:10],
            'n_passed': len(passed),
        }, f, indent=2, default=str)

if __name__ == '__main__':
    main()