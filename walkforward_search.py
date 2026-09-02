#!/usr/bin/env python3
"""Walk-forward governed parameter search for the Alpha momentum family.

Pre-registered protocol: experiments/PR_20260819_walkforward_grid.json
  - Grid: 108 configs (K x TP/SL x H x direction), fixed sizing/fees
  - 4 chronological folds per symbol, 50-bar embargo per fold
  - Selection on folds 1-3 (frequency + persistence), single OOS test on fold 4
  - Gates G1-G4; verdict PASS iff all hold, else NO-GO
Causal engine (backtest_alpha2.run_strategy), 0.1%/side fees, 3% sizing.
"""

import itertools
import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_alpha2 import run_strategy, ASSETS, DATA_DIR, CAP, FEE

OUT = Path('/home/nkhekhe/alpha_system/experiments/walkforward_results_20260819.json')
PR_HASH = '26f240bddba3950faf3f773df3ed3ed21d15bab04dc5ae3d22caf6c2aa79a9ae'

FOLDS = 4
EMBARGO = 50
K_GRID = [5, 10, 15, 20, 30, 40]
BARRIER_GRID = [0.01, 0.02, 0.03]
H_GRID = [10, 15, 30]
DIR_GRID = ['long', 'both']
FIXED = {'pos_pct': 0.03, 'max_consec': 3, 'cooldown': 50, 'warmup': 25}

configs = []
for k, b, h, d in itertools.product(K_GRID, BARRIER_GRID, H_GRID, DIR_GRID):
    configs.append({'momentum_k': k, 'tp': b, 'sl': b, 'horizon': h,
                    'direction': d, **FIXED})
assert len(configs) == 108, len(configs)

symbols = list(ASSETS.keys())
folds = {}


def run_job(job):
    sym, fi = job
    df = pd.read_feather(DATA_DIR / ASSETS[sym])
    df.attrs['symbol'] = sym
    idx = np.arange(len(df))
    ix = np.array_split(idx, FOLDS)[fi]
    start = min(ix[0] + EMBARGO, ix[-1])
    seg = df.iloc[start:ix[-1] + 1].copy()
    seg.attrs['symbol'] = sym
    out = []
    for ci, c in enumerate(configs):
        params = dict(c)
        trades, eq, dd = run_strategy(seg, capital=CAP, fees=FEE, params=params)
        n = len(trades)
        if n == 0:
            out.append((ci, {'n': 0, 'wr': 0.0, 'net_pnl': 0.0,
                             'net_return_pct': 0.0, 'mean_w': 0.0}))
            continue
        wins = sum(1 for t in trades if t['pnl_dollars'] > 0)
        out.append((ci, {
            'n': n,
            'wr': wins / n,
            'net_pnl': float(sum(t['pnl_dollars'] for t in trades)),
            'net_return_pct': float((eq - CAP) / CAP * 100),
            'mean_w': float(np.mean([t['pnl_pct'] for t in trades])),
        }))
    return sym, fi, out


def main():
    jobs = [(sym, fi) for sym in symbols for fi in range(FOLDS)]
    with Pool(4) as pool:
        results = pool.map(run_job, jobs)

    cells = {}
    for sym, fi, out in results:
        for ci, m in out:
            cells.setdefault(ci, {})[fi] = m

    per_fold = {}
    for fi in range(FOLDS):
        per_fold[fi] = {'n': 0, 'net_return_pct': 0.0, 'mean_w': []}
    for ci, m in cells.items():
        for fi in range(FOLDS):
            per_fold[fi]['n'] += m[fi]['n']
            per_fold[fi]['net_return_pct'] += m[fi]['net_return_pct']
            if m[fi]['n']:
                per_fold[fi]['mean_w'].append(m[fi]['mean_w'])

    deep = next(i for i, c in enumerate(configs)
                if c['momentum_k'] == 10 and c['tp'] == 0.02 and c['sl'] == 0.02
                and c['horizon'] == 15 and c['direction'] == 'both')
    assert configs[deep]['direction'] == 'both'

    def agg(ci, folds_sel):
        n = sum(cells[ci][fi]['n'] for fi in folds_sel)
        rets = [cells[ci][fi]['net_return_pct'] for fi in folds_sel]
        return {'n': n, 'median_ret': float(np.median(rets)), 'rets': rets}

    rows = []
    for ci, c in enumerate(configs):
        train = agg(ci, [0, 1, 2])
        g1 = all(cells[ci][fi]['n'] >= 20 for fi in range(FOLDS))
        g2 = sum(1 for fi in [0, 1, 2] if cells[ci][fi]['net_return_pct'] > 0) >= 2
        rows.append({'config': c, 'g1': g1, 'g2': g2, 'train': train})
    passing = [r for r in rows if r['g1'] and r['g2']]
    selected = max(passing, key=lambda r: r['train']['median_ret']) if passing else None

    out = {'pr_hash': PR_HASH, 'n_configs': len(configs), 'folds': FOLDS,
           'per_fold_totals': per_fold, 'selected': None, 'verdict': 'NO-GO', 'gates': {}}
    if selected:
        ci = configs.index(selected['config'])
        v = cells[ci][3]
        g3 = v['net_return_pct'] > 0
        g4 = v['mean_w'] > 0.002
        verdict = 'PASS' if (g3 and g4) else 'NO-GO'
        out['selected'] = {
            'config': selected['config'],
            'train': selected['train'],
            'validation': v,
        }
        out['gates'] = {'G1_frequency': True, 'G2_persistence': True,
                        'G3_oos_positive': g3, 'G4_fee_hurdle': g4}
        out['verdict'] = verdict

    top10 = sorted(rows, key=lambda r: r['train']['median_ret'], reverse=True)[:10]
    deep_row = rows[deep]
    out['deep_baseline'] = {'train': deep_row['train'],
                            'validation': cells[deep][3],
                            'g1': deep_row['g1'], 'g2': deep_row['g2']}
    out['top10_train'] = [{'config': r['config'], 'train': r['train'],
                           'g1': r['g1'], 'g2': r['g2']} for r in top10]
    out['n_passing_train'] = len(passing)

    OUT.write_text(json.dumps(out, indent=2))
    print(f"Folds totals (BTC+ETH, net %):")
    for fi in range(FOLDS):
        t = per_fold[fi]
        print(f"  fold {fi+1}: n={t['n']:>6}  net={t['net_return_pct']:+7.2f}%")
    print(f"\nDeep baseline train median {deep_row['train']['median_ret']:+.2f}% "
          f"(g1={deep_row['g1']}, g2={deep_row['g2']}), "
          f"validation fold4: {cells[deep][3]['net_return_pct']:+.2f}%, n={cells[deep][3]['n']}")
    print(f"\nConfigs passing G1+G2 on train folds: {len(passing)} / 108")
    print(f"Selected: {selected['config'] if selected else None}")
    if selected:
        v = out['selected']['validation']
        print(f"  train median {selected['train']['median_ret']:+.2f}% | "
              f"fold4 net {v['net_return_pct']:+.2f}% | n={v['n']} | wr={v['wr']:.1%} | "
              f"mean_w={v['mean_w']:+.4f}")
        print(f"  G3={out['gates']['G3_oos_positive']} G4={out['gates']['G4_fee_hurdle']}")
    print(f"\nTop-10 by train median:")
    for r in top10:
        c = r['config']
        print(f"  K{c['momentum_k']:>2} TP{c['tp']:.2f} SL{c['sl']:.2f} H{c['horizon']:>2} "
              f"{c['direction']:>4}: train {r['train']['median_ret']:+6.2f}% "
              f"(g1={r['g1']}, g2={r['g2']})")
    print(f"\n>>> VERDICT: {out['verdict']} <<<")
    print(f"Saved: {OUT}")


if __name__ == '__main__':
    main()