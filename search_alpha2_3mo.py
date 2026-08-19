#!/usr/bin/env python3
"""NK-EXP-W8-4: 3-month window governed search (432 vol-barrier combos, IS only).

Stages (per dry_data/alpha2_3mo_prereg.json):
  S1 selection: IS 2026-05-16 -> 2026-07-28 (21,197 bars), 5-fold CPCV,
     gates: trades>=100, barrier hit>=5%, Sharpe>0 in >=60% folds.
  S2 MC robustness on top-5 (bootstrap 1000x + noise 100).
  S3 single OOS eval 2026-07-28 -> 08-16 (5,300 bars) -> GO/NO-GO.
Final verdict compares vs Alpha-1 benchmarks (real same-window + synthetic doc).
"""

import json, sys, time
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/nkhekhe/alpha_system')
import backtest_alpha2 as bt
from search_alpha2 import evaluate_combo

DATA_DIR = Path('/home/nkhekhe/user_data/data/binance')
PREREG = json.load(open('/home/nkhekhe/alpha_system/dry_data/alpha2_3mo_prereg.json'))
ASSETS = {'BTCUSDT': 'BTC_USDT-5m.feather', 'ETHUSDT': 'ETH_USDT-5m.feather'}
WINDOW_START = pd.Timestamp('2026-05-16 05:35:00+00:00')
WINDOW_END = pd.Timestamp('2026-08-16 05:35:00+00:00')
FEE = 0.001
CAP = 100000.0

def build_combos(space):
    combos = []
    for ks in space['k_sigma']:
        for N in space['vol_lookback_N']:
            for h in space['horizon_H']:
                for k in space['momentum_k']:
                    for z in space['entry_z']:
                        combos.append({'momentum_k': k, 'tp': 0.02, 'sl': 0.02, 'horizon': h,
                                       'pos_pct': 0.03, 'max_consec': 3, 'cooldown': 50,
                                       'warmup': 25, 'direction': 'both',
                                       'k_sigma': ks, 'vol_lookback': N, 'entry_z': z})
    return combos

def mc_bootstrap(trades, n_resample=1000, seed=42):
    rng = np.random.default_rng(seed)
    rets = np.array([t['pnl_pct'] for t in trades])
    if len(rets) < 5:
        return 0.0, 0.0
    block = max(1, int(np.mean([t['hold_bars'] for t in trades])))
    n = len(rets)
    period_years = (pd.Timestamp(trades[-1]['exit_time']) - pd.Timestamp(trades[0]['entry_time'])).total_seconds() / (365*24*3600)
    sharpes = []
    for _ in range(n_resample):
        idx = []
        while len(idx) < n:
            start = rng.integers(0, n)
            idx.extend(range(start, min(start + block, n)))
        sub = rets[idx[:n]]
        sd = sub.std(ddof=1)
        if sd == 0:
            sharpes.append(0.0)
        else:
            npy = n / period_years if period_years > 0 else 0
            sharpes.append((sub.mean() / sd) * np.sqrt(npy))
    return float(np.percentile(sharpes, 5)), float(np.mean(sharpes))

def mc_noise(trades, n_paths=100, vol_scale=1.0, seed=7):
    rng = np.random.default_rng(seed)
    rets = np.array([t['pnl_pct'] for t in trades])
    sd = rets.std(ddof=1)
    period_years = (pd.Timestamp(trades[-1]['exit_time']) - pd.Timestamp(trades[0]['entry_time'])).total_seconds() / (365*24*3600)
    n = len(rets)
    npy = n / period_years if period_years > 0 else 0
    pos = 0
    for _ in range(n_paths):
        sub = rets + rng.normal(0, sd * vol_scale, n)
        s = sub.std(ddof=1)
        sh = (sub.mean() / s) * np.sqrt(npy) if s > 0 else 0.0
        if sh > 0:
            pos += 1
    return pos / n_paths

def main():
    sp = PREREG['search_space']
    combos = build_combos(sp)
    assert len(combos) == PREREG['total_combos'], f"combo count mismatch: {len(combos)}"

    print("=" * 78)
    print(f"  {PREREG['registration_id']} — 3-MONTH WINDOW VOL-BARRIER SEARCH")
    print("=" * 78)

    full = {}
    for sym, fname in ASSETS.items():
        df = pd.read_feather(DATA_DIR / fname)
        df.attrs['symbol'] = sym
        df = df[(df['date'] >= WINDOW_START) & (df['date'] <= WINDOW_END)].reset_index(drop=True)
        full[sym] = df
    cutoff = WINDOW_START + (WINDOW_END - WINDOW_START) * 0.8
    is_data = {s: df[df['date'] < cutoff].reset_index(drop=True) for s, df in full.items()}
    oos_data = {s: df[df['date'] >= cutoff].reset_index(drop=True) for s, df in full.items()}
    print(f"  Window: {WINDOW_START} -> {WINDOW_END} | IS: {len(is_data['BTCUSDT']):,} bars | OOS: {len(oos_data['BTCUSDT']):,} bars (cutoff {cutoff})")

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
    print(f"\n  Done {time.time()-t0:.0f}s | passing S1 gates: {len(passed)}/{len(results)}")

    print("\n  TOP 12 (IS):")
    print(f"  {'kσ':>4} {'N':>4} {'H':>4} {'k':>3} {'z':>4} | {'trd':>5} {'bar%':>5} {'WR%':>5} {'medSh':>7} {'+fld':>5} {'PnL%':>7}")
    for r in results[:12]:
        c = r['combo']
        print(f"  {c['k_sigma']:>4} {c['vol_lookback']:>4} {c['horizon']:>4} {c['momentum_k']:>3} {c['entry_z']:>4} | "
              f"{r['trades']:>5} {r['barrier_hit_rate']:>5.1f} {r['win_rate']:>5.1f} {r['median_sharpe']:>7.2f} "
              f"{r['pos_folds']*100:>4.0f}% {r['net_return_pct']:>+7.2f}")

    out = {'registration': PREREG['registration_id'], 'cutoff': str(cutoff),
           'n_combos': len(combos), 'passed': passed, 'top12': results[:12]}

    if not passed:
        out['verdict'] = 'NO-GO at selection stage (OOS not consumed)'
        print("\n  >>> NO PARAMS PASS SELECTION GATES <<<  (OOS not consumed)")
    else:
        top5 = passed[:5]
        print(f"\n  S2: MC robustness on top-5")
        for r in top5:
            c = r['combo']
            q5, mean = mc_bootstrap(r, n_resample=PREREG['mc_robustness']['stationary_bootstrap_resamples'])
            np_ = mc_noise(r, n_paths=PREREG['mc_robustness']['noise_paths'],
                           vol_scale=PREREG['mc_robustness']['noise_vol_scale'])
            ok = (q5 > PREREG['mc_robustness']['require_5th_percentile_sharpe_gt']
                  and np_ > PREREG['mc_robustness']['require_noise_pass_rate_gt'])
            print(f"    kσ={c['k_sigma']} N={c['vol_lookback']} H={c['horizon']} k={c['momentum_k']} z={c['entry_z']} | "
                  f"bootstrap5%={q5:+.2f} mean={mean:+.2f} noise_pass={np_:.2f} -> {'PASS' if ok else 'FAIL'}")
            r['mc'] = {'bootstrap_5pct': q5, 'bootstrap_mean': mean, 'noise_pass_rate': np_}
        mc_passed = [r for r in top5
                     if r['mc']['bootstrap_5pct'] > 0.0 and r['mc']['noise_pass_rate'] > 0.5]

        if not mc_passed:
            out['verdict'] = 'NO-GO at MC robustness (OOS not consumed)'
            print("\n  >>> NO CANDIDATE SURVIVES MC ROBUSTNESS <<<  (OOS not consumed)")
        else:
            cand = mc_passed[0]
            c = cand['combo']
            print(f"\n  S3: single OOS evaluation — best MC survivor kσ={c['k_sigma']} N={c['vol_lookback']} H={c['horizon']} k={c['momentum_k']} z={c['entry_z']}")
            oos_trades, oos_eq, oos_dd = [], CAP, 0.0
            for sym, df in oos_data.items():
                tr, eq, dd = bt.run_strategy(df, capital=CAP, fees=FEE, params=c)
                oos_trades.extend(tr)
                oos_eq = CAP + sum(t['pnl_dollars'] for t in oos_trades)
                oos_dd = max(oos_dd, dd)
            oos_trades.sort(key=lambda t: t['entry_time'])
            n_oos = len(oos_trades)
            oos_ret = (oos_eq / CAP - 1) * 100
            oos_sharpe = bt.sharpe_from_trades(oos_trades, (cutoff - WINDOW_START).total_seconds() / (365 * 24 * 3600))
            oos_wr = sum(1 for t in oos_trades if t['pnl_dollars'] > 0) / n_oos * 100 if n_oos else 0
            bh_ret = (oos_data['BTCUSDT']['close'].iloc[-1] / oos_data['BTCUSDT']['close'].iloc[0] - 1) * 100
            og = PREREG['oos_gates']
            ok = (n_oos >= og['min_trades'] and oos_sharpe > og['net_sharpe_gt']
                  and oos_ret > bh_ret)
            print(f"    OOS: {n_oos} trades, WR {oos_wr:.1f}%, net {oos_ret:+.2f}%, Sharpe {oos_sharpe:+.2f}, B&H {bh_ret:+.2f}%")
            print(f"    Gates (trades>={og['min_trades']}, Sharpe>0, beat B&H): {'PASS' if ok else 'FAIL'}")
            cand['oos'] = {'trades': n_oos, 'win_rate': oos_wr, 'return_pct': oos_ret,
                           'sharpe': oos_sharpe, 'buy_hold': bh_ret}
            out['candidate'] = cand
            out['verdict'] = 'GO (pending comparison vs Alpha 1 benchmarks)' if ok else 'NO-GO at OOS'
            print(f"  >>> OOS VERDICT: {out['verdict']} <<<")

    with open('/home/nkhekhe/alpha_system/dry_data/alpha2_3mo_results.json', 'w') as f:
        json.dump(out, f, indent=2, default=str)

if __name__ == '__main__':
    main()