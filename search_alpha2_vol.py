#!/usr/bin/env python3
"""NK-EXP-W8-3: vol-scaled barrier + z-filter search (432 combos, IS only)."""

import json, sys, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest_alpha2 as bt
from search_alpha2 import evaluate_combo

DATA_DIR = Path('/home/nkhekhe/user_data/data/binance')
PREREG = json.load(open('/home/nkhekhe/alpha_system/dry_data/alpha2_volbarrier_prereg.json'))
ASSETS = {'BTCUSDT': 'BTC_USDT-5m.feather', 'ETHUSDT': 'ETH_USDT-5m.feather'}
FEE = 0.001
CAP = 100000.0

def main():
    sp = PREREG['search_space']
    combos = []
    for ks in sp['k_sigma']:
        for N in sp['vol_lookback_N']:
            for h in sp['horizon_H']:
                for k in sp['momentum_k']:
                    for z in sp['entry_z']:
                        combos.append({'momentum_k': k, 'tp': 0.02, 'sl': 0.02, 'horizon': h,
                                       'pos_pct': 0.03, 'max_consec': 3, 'cooldown': 50,
                                       'warmup': 25, 'direction': 'both',
                                       'k_sigma': ks, 'vol_lookback': N, 'entry_z': z})
    assert len(combos) == PREREG['total_combos'], f"combo count mismatch: {len(combos)}"

    print("=" * 78)
    print(f"  {PREREG['registration_id']} — VOL-SCALED BARRIER + Z-FILTER SEARCH")
    print("=" * 78)

    full = {}
    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA_DIR / fname)
        df.attrs['symbol'] = sym
        full[sym] = df
    cutoff = full['BTCUSDT']['date'].iloc[-1] - (full['BTCUSDT']['date'].iloc[-1] - full['BTCUSDT']['date'].iloc[0]) * 0.2
    is_data = {sym: df[df['date'] < cutoff].reset_index(drop=True) for sym, df in full.items()}
    print(f"  IS: {len(is_data['BTCUSDT']):,} bars | cutoff {cutoff} | combos {len(combos)}")

    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(evaluate_combo, c, is_data) for c in combos]
        for i, f in enumerate(futures):
            results.append(f.result())
            if (i + 1) % 108 == 0:
                print(f"    {i+1}/{len(combos)} done ({time.time()-t0:.0f}s)")
    results.sort(key=lambda r: r['median_sharpe'], reverse=True)

    gates = PREREG['selection_gates']
    passed = [r for r in results
              if r['trades'] >= gates['min_trades']
              and r['barrier_hit_rate'] >= gates['min_barrier_hit_rate'] * 100
              and r['pos_folds'] >= gates['min_folds_positive_sharpe']]
    print(f"\n  Done {time.time()-t0:.0f}s | passing gates: {len(passed)}/{len(results)}")

    print("\n  TOP 12:")
    print(f"  {'kσ':>4} {'N':>4} {'H':>4} {'k':>3} {'z':>4} | {'trd':>5} {'bar%':>5} {'WR%':>5} {'medSh':>7} {'+fld':>5} {'PnL%':>7}")
    for r in results[:12]:
        c = r['combo']
        print(f"  {c['k_sigma']:>4} {c['vol_lookback']:>4} {c['horizon']:>4} {c['momentum_k']:>3} {c['entry_z']:>4} | "
              f"{r['trades']:>5} {r['barrier_hit_rate']:>5.1f} {r['win_rate']:>5.1f} {r['median_sharpe']:>7.2f} "
              f"{r['pos_folds']*100:>4.0f}% {r['net_return_pct']:>+7.2f}")

    if not passed:
        print("\n  >>> NO PARAMS PASS SELECTION GATES <<<  (OOS not consumed)")
        verdict = 'NO-GO at selection stage'
    else:
        print(f"\n  TOP-5 PASSING (-> MC robustness):")
        for r in passed[:5]:
            c = r['combo']
            print(f"    kσ={c['k_sigma']} N={c['vol_lookback']} H={c['horizon']} k={c['momentum_k']} z={c['entry_z']} | "
                  f"trades={r['trades']} medSharpe={r['median_sharpe']:.2f} PnL={r['net_return_pct']:+.2f}%")
        verdict = 'MC_STAGE'

    with open('/home/nkhekhe/alpha_system/dry_data/alpha2_volbarrier_results.json', 'w') as f:
        json.dump({'registration': PREREG['registration_id'], 'cutoff': str(cutoff),
                   'n_combos': len(combos), 'passed': passed, 'top12': results[:12],
                   'verdict': verdict}, f, indent=2, default=str)

if __name__ == '__main__':
    main()